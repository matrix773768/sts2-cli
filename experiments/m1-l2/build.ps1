$ErrorActionPreference = 'Stop'
$base=(Resolve-Path CombatSolver-m1-cs1).Path
$src="$base/CombatSolver-78e4545e825e58c3d999354b1ffcd54241b1d2cf"
$exp=(New-Item -ItemType Directory CombatSolver-m1-l2 -Force).FullName
$probe="$exp/OfflineSearchHarness"
New-Item -ItemType Directory $probe -Force | Out-Null
Get-ChildItem "$src/tools/search/OfflineSearchHarness" -File | Copy-Item -Destination $probe

Copy-Item "$PSScriptRoot/../m1-l1/CandidateProbe.cs" $probe
$runtime="$probe/ModRuntime.cs"
$original=[IO.File]::ReadAllText($runtime)
$anchor='        object describedPolicy = DescribePolicy(policy);'
if ([regex]::Matches($original,[regex]::Escape($anchor)).Count -ne 1) { throw 'Unexpected ModRuntime source' }
$hook='        if (Environment.GetEnvironmentVariable("M1L2_PREFIX") == "1")
        {
            CandidateProbe.Run(root, names, damage, policy with
            {
                Profile = policy.Profile with { SoftTimeBudgetMilliseconds = options.BudgetMilliseconds },
            }, loop, options.OutputDirectory, captureWitnesses: true);
            if (ContinuationStamp.CaptureLive(state).StateText != root.LiveStamp.StateText)
                throw new InvalidOperationException("M1-L2 changed the live state.");
        }'
[IO.File]::WriteAllText($runtime,$original.Replace($anchor,$hook + [Environment]::NewLine + $anchor))
$bin="$exp/.local/tool-build/OfflineSearchHarness/bin/Release/net9.0"
$env:DOTNET_CLI_HOME=(Resolve-Path sts2-cli/logs/dotnet-home).Path
$env:NUGET_PACKAGES=(Resolve-Path sts2-cli/logs/nuget-packages).Path
$env:OFFLINE_HARNESS_COMBATSOLVER_DLL="$base/baseline.dll"
if ((Get-FileHash $env:OFFLINE_HARNESS_COMBATSOLVER_DLL).Hash -ne 'D286A18C7C0A06769AA636EC00CAC53F3FB71DE749028858C1E1A7062282AB13') { throw 'Unexpected baseline' }
dotnet build "$probe/OfflineSearchHarness.csproj" -c Release "-p:SteamRoot=$env:USERPROFILE/Desktop/STEAM" "-p:CombatSolverRepositoryRoot=$src" "-p:CombatSolverDll=$base/baseline.dll" -p:NuGetAudit=false -o $bin
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
