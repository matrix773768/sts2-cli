param([string]$Results = 'CombatSolver-m1-cs4/results', [switch]$NativeOnly)
$ErrorActionPreference = 'Stop'
$base=(Resolve-Path CombatSolver-m1-cs1).Path
$src="$base/CombatSolver-78e4545e825e58c3d999354b1ffcd54241b1d2cf"
$exp=(New-Item -ItemType Directory CombatSolver-m1-cs4 -Force).FullName
$probe="$exp/OfflineSearchHarness"
New-Item -ItemType Directory $probe -Force | Out-Null
Get-ChildItem "$src/tools/search/OfflineSearchHarness" -File | Copy-Item -Destination $probe
Copy-Item "$PSScriptRoot/DistributionProbe.cs" $probe
$program="$probe/Program.cs"
$original=[IO.File]::ReadAllText($program)
$anchor='            WriteProgress(options, "M1", "ok", "已到达玩家第一回合");'
if (!$original.Contains($anchor)) { throw 'Unexpected OfflineSearchHarness source' }
$hook='            DistributionProbe.Run(combat!, loop, options.OutputDirectory);'
[IO.File]::WriteAllText($program,$original.Replace($anchor,$anchor + [Environment]::NewLine + $hook))
$bin="$exp/.local/tool-build/OfflineSearchHarness/bin/Release/net9.0"
$env:DOTNET_CLI_HOME=(Resolve-Path sts2-cli/logs/dotnet-home).Path
$env:NUGET_PACKAGES=(Resolve-Path sts2-cli/logs/nuget-packages).Path
$env:OFFLINE_HARNESS_COMBATSOLVER_DLL="$base/baseline.dll"
if ((Get-FileHash $env:OFFLINE_HARNESS_COMBATSOLVER_DLL).Hash -ne 'D286A18C7C0A06769AA636EC00CAC53F3FB71DE749028858C1E1A7062282AB13') { throw 'Unexpected baseline' }
dotnet build "$probe/OfflineSearchHarness.csproj" -c Release "-p:SteamRoot=$env:USERPROFILE/Desktop/STEAM" "-p:CombatSolverRepositoryRoot=$src" "-p:CombatSolverDll=$base/baseline.dll" -p:NuGetAudit=false -o $bin
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
$failed = @()
foreach ($nativeOrder in '', '0,4,1,3,2', '1,2,4,3,0') {
    if ($NativeOnly -and !$nativeOrder) { continue }
    $env:M1CS4_NATIVE_ORDER=$nativeOrder
    $label=if($nativeOrder){$nativeOrder.Replace(',','')}else{'enumeration'}
    & sts2-cli/logs/m1-review-dotnet/dotnet.exe --fx-version 9.0.7 "$bin/OfflineSearchHarness.dll" --character IRONCLAD --encounter FUZZY_WURM_CRAWLER_WEAK --seed M1CS1 --out "$Results/$label" --milestone M1 --dop 1
    if ($LASTEXITCODE -ne 0) { $failed += "$label (exit $LASTEXITCODE)" }
}
if ($failed.Count) { throw ($failed -join ', ') }
