param([switch]$Repair)
$ErrorActionPreference = 'Stop'
$base=(Resolve-Path CombatSolver-m1-cs1).Path
$src="$base/CombatSolver-78e4545e825e58c3d999354b1ffcd54241b1d2cf"
$target = if ($Repair) { "CombatSolver-m1-q2/repair" } else { "CombatSolver-m1-q2" }
$work=(New-Item -ItemType Directory $target -Force).FullName
$probe="$work/OfflineSearchHarness"
New-Item -ItemType Directory $probe -Force | Out-Null
Get-ChildItem "$src/tools/search/OfflineSearchHarness" -File | Copy-Item -Destination $probe
Copy-Item "$PSScriptRoot/../m1-h1/NativeWitness.cs" $probe
$fast = [IO.File]::ReadAllText((Join-Path $PSScriptRoot '../m1-q1/FastCombat.cs'))
function Instrument($anchor, $replacement) {
    if ([regex]::Matches($script:fast,[regex]::Escape($anchor)).Count -ne 1) { throw "Unexpected Q1 source at $anchor" }
    $script:fast = $script:fast.Replace($anchor,$replacement)
}
Instrument '        InstallHooks();' @"
        object Resources() => new
        {
            player.Gold, maxHp = player.Creature.MaxHp,
            cards = player.Deck.Cards.Select(card => CardChoiceSupport.ChoiceCardKey(card)).ToArray(),
            relics = player.Relics.Select(relic => relic.Id.Entry).ToArray(),
            potions = player.PotionSlots.Select(potion => potion?.Id.Entry).ToArray(),
        };
        var initialResources = Resources();
        File.WriteAllText(Path.Combine(output, "identity.json"), JsonSerializer.Serialize(new
        {
            root = Hash(root.ContinuationStamp.StateText), live = Hash(root.LiveStamp.StateText),
            resources = initialResources,
        }, UnattendedTestFiles.JsonOptions));
        InstallHooks();
"@
Instrument '                block = visible.Block, enemies = visible.Enemies });' '                block = visible.Block, enemies = visible.Enemies, moves = visible.Moves });'
Instrument '            peakMiB = Process.GetCurrentProcess().PeakWorkingSet64 / 1048576.0, steps,' '            peakMiB = Process.GetCurrentProcess().PeakWorkingSet64 / 1048576.0, steps, initialResources, finalResources = Resources(),'
if ($Repair) {
    Copy-Item "$PSScriptRoot/ReattachPresentation.cs" $probe
    Instrument "        InstallHooks();" ("        ReattachPresentation.Install();" + [Environment]::NewLine + "        InstallHooks();")
}
[IO.File]::WriteAllText("$probe/FastCombat.cs",$fast)
$p="$probe/Program.cs"
$t=[IO.File]::ReadAllText($p)
$anchor='            WriteProgress(options, "M1", "ok", "已到达玩家第一回合");'
if ([regex]::Matches($t,[regex]::Escape($anchor)).Count -ne 1) { throw 'Unexpected harness source' }
$hook='            FastCombat.Run(combat!, loop, options.OutputDirectory);'
[IO.File]::WriteAllText($p,$t.Replace($anchor,$anchor + [Environment]::NewLine + $hook))
$bin="$work/bin"
$env:DOTNET_CLI_HOME=(Resolve-Path sts2-cli/logs/dotnet-home).Path
$env:NUGET_PACKAGES=(Resolve-Path sts2-cli/logs/nuget-packages).Path
$env:OFFLINE_HARNESS_COMBATSOLVER_DLL="$base/baseline.dll"

if ((Get-FileHash $env:OFFLINE_HARNESS_COMBATSOLVER_DLL).Hash -ne 'D286A18C7C0A06769AA636EC00CAC53F3FB71DE749028858C1E1A7062282AB13') { throw 'Unexpected solver DLL' }
dotnet build "$probe/OfflineSearchHarness.csproj" -c Release "-p:SteamRoot=$env:USERPROFILE/Desktop/STEAM" "-p:CombatSolverRepositoryRoot=$src" "-p:CombatSolverDll=$base/baseline.dll" -p:NuGetAudit=false -o $bin
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
