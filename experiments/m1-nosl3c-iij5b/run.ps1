param(
    [string]$Prefix = 'iij5b-serial',
    [string]$Solver = 'logs/iij4-solver',
    [string[]]$Stages = @('identity','archive','risks','samples','pair16','holdout','training','main')
)

$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$accept = 'experiments/m1-nosl3c-iij5b/accept.py'
$ledgers = @('logs/nosl3c-iic-random-final','logs/nosl3c-iid-release-independent','logs/nosl3c-iie-broad')
$cases = @('--case','nosl3c-iic-random-final:0:3',
    '--case','nosl3c-iid-release-independent:0:9',
    '--case','nosl3c-iid-release-independent:0:25',
    '--case','nosl3c-iid-release-independent:0:27',
    '--case','nosl3c-iid-release-independent:0:28',
    '--case','nosl3c-iie-broad:1:0','--case','nosl3c-iie-broad:1:2',
    '--case','nosl3c-iie-broad:1:3')

function Invoke-Check([string]$Name, [string[]]$Arguments, [string]$OutputFile) {
    $log = if ($OutputFile) { $OutputFile } else { "logs/$Prefix-$Name.log" }
    $timing = "logs/$Prefix-$Name-time.json"
    if ((Test-Path $log) -or (Test-Path $timing)) {
        throw "Output already exists for $Name"
    }
    $timer = [Diagnostics.Stopwatch]::StartNew()
    & python @Arguments *> $log
    $code = $LASTEXITCODE
    @{name=$Name; seconds=$timer.Elapsed.TotalSeconds; exit=$code} |
        ConvertTo-Json -Compress | Set-Content $timing -Encoding utf8
    Write-Host "$Name exit=$code ($([Math]::Round($timer.Elapsed.TotalSeconds, 1))s)"
    return $code
}

$failed = $false
foreach ($stage in $Stages) {
    switch ($stage) {
        identity {
            $code = Invoke-Check identity @($accept,'identity',"logs/$Prefix-identity",$Solver)
            if ($code) { throw 'Build identity did not attest' }
            $mainHash = '870674119125fa806128896e671d56ded10b76cd00ea0f53485f4a2246768668'
            if ((Get-FileHash logs/iih9-main-host/bin/Debug/net9.0/Sts2Headless.dll).Hash -ne $mainHash) {
                throw 'Unexpected regular Headless hash'
            }
        }
        archive {
            $code = Invoke-Check archive (@($accept,'replay',"logs/$Prefix-archive") +
                $ledgers + @('--solver',$Solver,'--workers','2'))
        }
        risks {
            $code = Invoke-Check risks @($accept,'risks',"logs/$Prefix-risks",$Solver)
            $prefixCode = Invoke-Check prefix (@('experiments/m1-nosl3c-iii8/verify_root.py',
                'prefix',"logs/$Prefix-prefix") + $ledgers + @('--solver',$Solver) + $cases)
            if ($prefixCode) { $code = $prefixCode }
        }
        samples {
            $code = 0
            foreach ($group in @(1,2,3,4,6,7,8)) {
                $file = if ($group -eq 1) { 'verify_roots.py' } else { 'verify_root.py' }
                $groupCode = Invoke-Check "sample-$group" @("experiments/m1-nosl3c-iii$group/$file",
                    'resample',"logs/$Prefix-sample-$group",$Solver)
                if ($groupCode) { $code = $groupCode }
            }
        }
        { $_ -in @('pair16','holdout') } {
            $code = Invoke-Check $stage @($accept,'train',"logs/$Prefix-$stage",'--solver',
                $Solver,'--suite',$stage,'--workers','2')
        }
        training {
            $code = 0
            foreach ($mode in @('cold','resume')) {
                $argsForMode = @($accept,'train',"logs/$Prefix-$mode",'--solver',$Solver,
                    '--suite','e3-update','--workers','2')
                $code = Invoke-Check "$mode-init" ($argsForMode + @('--through-update','0'))
                if ($code) { break }
                $code = Invoke-Check "$mode-seed" @($accept,'seed',"logs/$Prefix-pair16","logs/$Prefix-$mode")
                if ($code) { break }
                if ($mode -eq 'resume') {
                    $code = Invoke-Check resume-first ($argsForMode + @('--through-update','1'))
                    if ($code) { break }
                }
                $code = Invoke-Check $mode $argsForMode
                if ($code) { break }
            }
            if (!$code) {
                $code = Invoke-Check journals @('experiments/m1-nosl3c-iih3-stabilization/compare_journals.py',
                    "logs/$Prefix-cold/training.sqlite","logs/$Prefix-resume/training.sqlite") "logs/$Prefix-journals.json"
            }
        }
        main {
            $env:PYTHONPATH = (Resolve-Path logs/iig-completion-test-deps).Path
            $env:DOTNET_CLI_HOME = (Resolve-Path logs/dotnet-home).Path
            $env:NUGET_PACKAGES = (Resolve-Path logs/nuget-packages).Path
            $env:PATH = (Resolve-Path logs/m1-review-dotnet).Path + [IO.Path]::PathSeparator + $env:PATH
            $test = 'from pathlib import Path; import sys; sys.path.insert(0, "python"); import headless_runtime, pytest; headless_runtime.ENGINE = Path("logs/iih9-main-host/bin/Debug/net9.0/Sts2Headless.dll").resolve(); raise SystemExit(pytest.main(sys.argv[1:]))'
            $code = Invoke-Check main-pytest @('-c',$test,'-q','-rA','tests',"--junitxml=logs/$Prefix-main.xml")
        }
        default { throw "Unknown stage $stage" }
    }
    if ($code) { $failed = $true }
}
if ($failed) { exit 1 }
