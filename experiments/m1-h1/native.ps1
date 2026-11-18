param([string]$Source = 'CombatSolver-m1-h1/measured/dev-02-defect-elite', [string]$Output = 'CombatSolver-m1-h1/native')
$ErrorActionPreference = 'Stop'
$base=(Resolve-Path CombatSolver-m1-cs1).Path
$src="$base/CombatSolver-78e4545e825e58c3d999354b1ffcd54241b1d2cf"
$work=(New-Item -ItemType Directory CombatSolver-m1-h1 -Force).FullName
$probe="$work/OfflineSearchHarness"
New-Item -ItemType Directory $probe -Force | Out-Null
Get-ChildItem "$src/tools/search/OfflineSearchHarness" -File | Copy-Item -Destination $probe
Copy-Item "$PSScriptRoot/NativeWitness.cs" $probe
$p="$probe/Program.cs"
$t=[IO.File]::ReadAllText($p)
$anchor='            WriteProgress(options, "M1", "ok", "已到达玩家第一回合");'
if ([regex]::Matches($t,[regex]::Escape($anchor)).Count -ne 1) { throw 'Unexpected harness source' }
$hook='            NativeWitness.Run(combat!, loop, Environment.GetEnvironmentVariable("M1H1_WITNESS")!, options.OutputDirectory);'
[IO.File]::WriteAllText($p,$t.Replace($anchor,$anchor + [Environment]::NewLine + $hook))
$bin="$work/bin"
$env:DOTNET_CLI_HOME=(Resolve-Path sts2-cli/logs/dotnet-home).Path
$env:NUGET_PACKAGES=(Resolve-Path sts2-cli/logs/nuget-packages).Path
$env:OFFLINE_HARNESS_COMBATSOLVER_DLL="$base/baseline.dll"
$env:M1H1_WITNESS=(Resolve-Path $Source).Path
if ((Get-FileHash $env:OFFLINE_HARNESS_COMBATSOLVER_DLL).Hash -ne 'D286A18C7C0A06769AA636EC00CAC53F3FB71DE749028858C1E1A7062282AB13') { throw 'Unexpected solver DLL' }
dotnet build "$probe/OfflineSearchHarness.csproj" -c Release "-p:SteamRoot=$env:USERPROFILE/Desktop/STEAM" "-p:CombatSolverRepositoryRoot=$src" "-p:CombatSolverDll=$base/baseline.dll" -p:NuGetAudit=false -o $bin
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
& sts2-cli/logs/m1-review-dotnet/dotnet.exe --fx-version 9.0.7 "$bin/OfflineSearchHarness.dll" --request "$env:M1H1_WITNESS/request.json" --out $Output --milestone M1 --profile Custom --beam 24 --nodes 2400 --budget-ms 15000 --dop 2 --potion-policy Smart --search-mode Coordinator --use-portfolio --production-budget
if ($LASTEXITCODE -ne 0) { throw 'Native replay failed' }
