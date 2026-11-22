param([Parameter(Mandatory)][string]$Stage, [string]$Prefix = 'iik5')
$ErrorActionPreference = 'Stop'
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$root = 'experiments/m1-nosl3c-'
$accept = "${root}iik5/accept.py"
$solver = 'logs/iik3b-solver'
$hostPath = 'logs/iik4b-host-final'
function Invoke-Check([string]$Name, [string[]]$Arguments) {
    $log = "logs/$Prefix-$Name.log"
    $timing = "logs/$Prefix-$Name-time.json"
    if ((Test-Path $log) -or (Test-Path $timing)) { throw "Already exists: $Name" }
    $clock = [Diagnostics.Stopwatch]::StartNew()
    & python @Arguments *> $log
    $code = $LASTEXITCODE
    @{name=$Name; seconds=$clock.Elapsed.TotalSeconds; exit=$code} |
        ConvertTo-Json -Compress | Set-Content $timing -Encoding utf8
    Write-Host "$Name exit=$code seconds=$($clock.Elapsed.TotalSeconds)"
    if ($code) { throw "Failed: $Name" }
}
switch ($Stage) {
    fixtures {
        & "${root}iik4b/verify_signals.ps1" "$hostPath/Headless/bin/Debug/net9.0/GodotSharp.dll" > "logs/$Prefix-signals.log"
        $fixtures = [ordered]@{
            orb = 'iik21/verify_orbs.py'; rod = 'iik22/verify_rod.py'
            glass = 'iik23/verify_glass.py'; suck = 'iik24/verify_suck.py'
            cards = 'iik3b/verify_cards.py'; osty = 'iik1/verify_osty.py'
        }
        foreach ($entry in $fixtures.GetEnumerator()) {
            if ($entry.Key -ne "osty" -or !(Test-Path "logs/$Prefix-osty/fixture.json")) {
                Invoke-Check $entry.Key @($accept,'script',"$root$($entry.Value)","logs/$Prefix-$($entry.Key)",$solver)
            }
            foreach ($file in Get-ChildItem "logs/$Prefix-$($entry.Key)" -Filter '*.json' -File) {
                $data = Get-Content $file.FullName -Raw | ConvertFrom-Json -Depth 100
                if ($data.engine.godot_sha256 -ne '82b8ecbc4fee2f6490a27aa1a509c48b646bf9f35e5bfad07699487a539ca9aa') {
                    throw "Wrong fixture host: $file"
                }
                foreach ($frame in (@($data.frames) + @($data.result))) {
                    if ($null -ne $frame -and $frame.differences -and $frame.differences.PSObject.Properties.Name) {
                        throw "Fixture difference: $file"
                    }
                }
            }
        }
        Invoke-Check boulder @("${root}iik4b/verify_host.py",'fixture',"logs/$Prefix-boulder",$solver,$hostPath)
    }
    archive {
        Invoke-Check archive @($accept,'replay',"logs/$Prefix-archive",'logs/nosl3c-iic-random-final',
            'logs/nosl3c-iid-release-independent','logs/nosl3c-iie-broad','--solver',$solver,'--workers','2')
    }
    prefix {
        $cases = @('--case','nosl3c-iic-random-final:0:3',
            '--case','nosl3c-iid-release-independent:0:9','--case','nosl3c-iid-release-independent:0:25',
            '--case','nosl3c-iid-release-independent:0:27','--case','nosl3c-iid-release-independent:0:28',
            '--case','nosl3c-iie-broad:1:0','--case','nosl3c-iie-broad:1:2','--case','nosl3c-iie-broad:1:3')
        Invoke-Check prefix (@($accept,'script',"${root}iii8/verify_root.py",'prefix',"logs/$Prefix-prefix",
            'logs/nosl3c-iic-random-final','logs/nosl3c-iid-release-independent','logs/nosl3c-iie-broad',
            '--solver',$solver) + $cases)
    }
    samples {
        foreach ($group in @(1,2,3,4,6,7,8)) {
            $file = if ($group -eq 1) {'verify_roots.py'} else {'verify_root.py'}
            Invoke-Check "sample-$group" @($accept,'script',"${root}iii$group/$file",'resample',
                "logs/$Prefix-sample-$group",$solver)
        }
    }
    { $_ -in @('pair16','holdout') } {
        Invoke-Check $Stage @($accept,'train',"logs/$Prefix-$Stage",'--solver',$solver,'--suite',$Stage,'--workers','2')
    }
    training {
        foreach ($mode in @('cold','resume')) {
            $argsForMode = @($accept,'train',"logs/$Prefix-$mode",'--solver',$solver,'--suite','e3-update','--workers','2')
            Invoke-Check "$mode-init" ($argsForMode + @('--through-update','0'))
            Invoke-Check "$mode-seed" @($accept,'seed',"logs/$Prefix-pair16","logs/$Prefix-$mode")
            if ($mode -eq 'resume') { Invoke-Check resume-first ($argsForMode + @('--through-update','1')) }
            Invoke-Check $mode $argsForMode
        }
        Invoke-Check journals @("${root}iih3-stabilization/compare_journals.py",
            "logs/$Prefix-cold/training.sqlite","logs/$Prefix-resume/training.sqlite")
        Copy-Item "logs/$Prefix-journals.log" "logs/$Prefix-journals.json"
    }
    main {
        $env:PYTHONPATH = (Resolve-Path logs/iig-completion-test-deps).Path
        $env:DOTNET_CLI_HOME = (Resolve-Path logs/dotnet-home).Path
        $env:NUGET_PACKAGES = (Resolve-Path logs/nuget-packages).Path
        $env:PATH = (Resolve-Path logs/m1-review-dotnet).Path + [IO.Path]::PathSeparator + $env:PATH
        $test = 'from pathlib import Path; import sys; sys.path.insert(0, "python"); import headless_runtime, pytest; headless_runtime.ENGINE = Path("logs/iik5-main-host/bin/Debug/net9.0/Sts2Headless.dll").resolve(); raise SystemExit(pytest.main(sys.argv[1:]))'
        Invoke-Check main-pytest @('-c',$test,'-q','-rA','tests',"--junitxml=logs/$Prefix-main.xml")
    }
    default { throw "Unknown stage $Stage" }
}
