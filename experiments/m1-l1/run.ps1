param([string]$Results = "CombatSolver-m1-l1/results", [string[]]$Cases = @("small","seapunk","pressure-queen"), [int]$Nodes = 1000)
$ErrorActionPreference = 'Stop'
$base=(Resolve-Path CombatSolver-m1-cs1).Path
$src="$base/CombatSolver-78e4545e825e58c3d999354b1ffcd54241b1d2cf"
$exp=(New-Item -ItemType Directory CombatSolver-m1-l1 -Force).FullName
$probe="$exp/OfflineSearchHarness"
New-Item -ItemType Directory $probe -Force | Out-Null
Get-ChildItem "$src/tools/search/OfflineSearchHarness" -File | Copy-Item -Destination $probe

Copy-Item "$PSScriptRoot/CandidateProbe.cs" $probe
$runtime="$probe/ModRuntime.cs"
$original=[IO.File]::ReadAllText($runtime)
$anchor='        object describedPolicy = DescribePolicy(policy);'
if ([regex]::Matches($original,[regex]::Escape($anchor)).Count -ne 1) { throw 'Unexpected ModRuntime source' }
$hook='        CandidateProbe.Run(root, names, damage, policy with
        {
            Profile = policy.Profile with { SoftTimeBudgetMilliseconds = 30000 },
        }, loop, options.OutputDirectory);
        if (ContinuationStamp.CaptureLive(state).StateText != root.LiveStamp.StateText)
            throw new InvalidOperationException("M1-L1 changed the live state.");'
[IO.File]::WriteAllText($runtime,$original.Replace($anchor,$hook + [Environment]::NewLine + $anchor))
$bin="$exp/.local/tool-build/OfflineSearchHarness/bin/Release/net9.0"
$env:DOTNET_CLI_HOME=(Resolve-Path sts2-cli/logs/dotnet-home).Path
$env:NUGET_PACKAGES=(Resolve-Path sts2-cli/logs/nuget-packages).Path
$env:OFFLINE_HARNESS_COMBATSOLVER_DLL="$base/baseline.dll"
if ((Get-FileHash $env:OFFLINE_HARNESS_COMBATSOLVER_DLL).Hash -ne 'D286A18C7C0A06769AA636EC00CAC53F3FB71DE749028858C1E1A7062282AB13') { throw 'Unexpected baseline' }
dotnet build "$probe/OfflineSearchHarness.csproj" -c Release "-p:SteamRoot=$env:USERPROFILE/Desktop/STEAM" "-p:CombatSolverRepositoryRoot=$src" "-p:CombatSolverDll=$base/baseline.dll" -p:NuGetAudit=false -o $bin
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }

foreach ($case in $Cases) {
    $folder=Join-Path $Results $case
    if (Test-Path $folder) { throw "Output exists: $folder" }
    $scenario = @('--request',"$base/fixtures/requests/$case.json")
    if ($case -in 'small','seapunk') {
        $encounter = if ($case -eq 'small') { 'FUZZY_WURM_CRAWLER_WEAK' } else { 'SEAPUNK_WEAK' }
        $scenario = @('--character','IRONCLAD','--encounter',$encounter,'--seed','M1CS1')
    }
    & sts2-cli/logs/m1-review-dotnet/dotnet.exe --fx-version 9.0.7 "$bin/OfflineSearchHarness.dll" @scenario --label $case --out $folder --profile Custom --search-mode Evaluate --beam 24 --nodes $Nodes --dop 1 --budget-ms 30000 --potion-policy Smart
    if ($LASTEXITCODE -ne 0) { throw "Harness failed for $case" }
}
