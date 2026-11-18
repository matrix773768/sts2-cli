param([switch]$Repair)
$ErrorActionPreference = 'Stop'
$base=(Resolve-Path CombatSolver-m1-cs1).Path
$src="$base/CombatSolver-78e4545e825e58c3d999354b1ffcd54241b1d2cf"
$target = if ($Repair) { "CombatSolver-m1-q4/repair" } else { "CombatSolver-m1-q4" }
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
    Copy-Item "$PSScriptRoot/../m1-q2/ReattachPresentation.cs" $probe
    Instrument "        InstallHooks();" ("        ReattachPresentation.Install();" + [Environment]::NewLine + "        InstallHooks();")
}
Copy-Item "$PSScriptRoot/../m1-q3/CombatChoices.cs" $probe
Instrument '        var selector = new UnsupportedChoice();' '        var selector = new CombatChoices(player, tactical, combat, Environment.GetEnvironmentVariable("M1Q3_VERIFY") == "1");'
Instrument '            int before = player.Creature.CurrentHp;' '            int before = player.Creature.CurrentHp;
            selector.Begin(i + 1, selected?.Id);'
Instrument '            double executeMs = Stopwatch.GetElapsedTime(start).TotalMilliseconds;' '            double executeMs = Stopwatch.GetElapsedTime(start).TotalMilliseconds;
            selector.Complete(status != "execution_timeout", _terminal == null && manager.IsInProgress && player.Creature.CurrentHp > 0);'
Instrument 'steps, initialResources, finalResources = Resources(),' 'steps, initialResources, finalResources = Resources(),
            choiceRequests = selector.Log, choiceChecks = selector.StateChecks, choiceFailure = selector.Failure,
            choiceObservationMs = selector.ObservationMs, choiceDecisionMs = selector.DecisionMs,'
Copy-Item "$PSScriptRoot/RiskAudit.cs" $probe
Instrument '        var battle = Stopwatch.StartNew();' '        var riskAudit = new RiskAudit(combat, player);
        riskAudit.Install();
        string arm = Environment.GetEnvironmentVariable("M1Q4_ARM") ?? "A";
        if (arm is not ("A" or "B" or "C")) throw new ArgumentException("Unknown Q4 arm");
        int interventions = 0;
        bool regent = player.Character.Id.Entry == "REGENT";
        var battle = Stopwatch.StartNew();'
Instrument '            long start = Stopwatch.GetTimestamp();' '            var preStamp = Hash(ContinuationStamp.CaptureLive(combat).StateText);
            riskAudit.Step = i + 1;
            long start = Stopwatch.GetTimestamp();'
Instrument '            var visible = Observe(combat);' '            var visible = Observe(combat);
            var riskBefore = riskAudit.Observe();'
Instrument '            Move? selected = Decide(visible, tactical);' '            Move? stock = Decide(visible, tactical);
            Move? selected = stock;
            if (arm == "C" || (arm == "B" && interventions == 0))
            {
                if (regent && stock?.Id == "THE_GAMBIT")
                    selected = Decide(visible with { Moves = visible.Moves.Where(m => m.Id != "THE_GAMBIT").ToList() }, tactical);
                if (!regent && riskBefore.Sandpit is int count && count > 0 && (arm == "B" || count <= 2))
                    selected = visible.Moves.FirstOrDefault(m => m.Id == "FRANTIC_ESCAPE") ?? stock;
                if (selected != stock) interventions++;
            }'
Instrument '                block = visible.Block, enemies = visible.Enemies, moves = visible.Moves });' '                block = visible.Block, enemies = visible.Enemies, moves = visible.Moves,
                stock, preStamp, riskBefore, riskAfter = riskAudit.Observe() });'
Instrument '            choiceRequests = selector.Log,' '            arm, interventions, lethalEvents = riskAudit.Events,
            damageToEnemies = CombatManager.Instance.History.Entries
                .OfType<MegaCrit.Sts2.Core.Combat.History.Entries.DamageReceivedEntry>()
                .Where(e => e.Receiver.Side == CombatSide.Enemy)
                .Sum(e => Math.Max(0, e.Result.UnblockedDamage - e.Result.OverkillDamage)),
            choiceRequests = selector.Log,'
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
