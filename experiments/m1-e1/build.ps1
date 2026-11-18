param([switch]$Repair, [switch]$TerminalParity, [switch]$TargetedSearch, [switch]$CrossMechanism)
$ErrorActionPreference = 'Stop'
$base=(Resolve-Path CombatSolver-m1-cs1).Path
$src="$base/CombatSolver-78e4545e825e58c3d999354b1ffcd54241b1d2cf"
$target = if ($Repair) { "CombatSolver-m1-e1/repair" } else { "CombatSolver-m1-e1" }
if ($TerminalParity) {
    if (!$Repair) { throw 'Terminal parity uses the Q3 repair harness' }
    $target = 'CombatSolver-m1-e2/repair'
}
if ($TargetedSearch) {
    if (!$TerminalParity) { throw 'Targeted search uses the terminal parity harness' }
    $target = 'CombatSolver-m1-q5/repair'
}
if ($CrossMechanism) {
    if (!$TargetedSearch) { throw 'Cross-mechanism search uses the targeted search harness' }
    $target = 'CombatSolver-m1-q6/repair'
}
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
Copy-Item "$PSScriptRoot/RouteProbe.cs" $probe
Instrument '        _finish = () => ledger.Capture(combat, ended: true);' '        using var route = new RouteProbe(combat, output);
        _finish = () => { route.CaptureTerminal(); return ledger.Capture(combat, ended: true); };'
Instrument '        if (warm)' '        if (warm && route.Ready)'
Instrument '            if (_terminal != null' '            if (!route.Ready || i >= route.Inputs.Length || _terminal != null'
Instrument '            Move? selected = Decide(visible, tactical);' '            var expected = route.Inputs[i].Selected;
            Move? selected = expected == null ? null : visible.Moves.Single(m => m.HandIndex == expected.HandIndex
                && m.Id == expected.Id && m.Target == expected.Target);
            if (!route.Predict(i)) break;'
Instrument '            if (selector.Requested || status == "execution_timeout")' '            if (!selector.Requested && status != "execution_timeout" && !route.Compare(i + 1)) break;
            if (selector.Requested || status == "execution_timeout")'
Instrument '        File.WriteAllText(Path.Combine(output, "fast.json")' '        route.Finish(status);
        File.WriteAllText(Path.Combine(output, "fast.json")'
if ($TerminalParity) {
    Copy-Item "$PSScriptRoot/../m1-e2/TerminalProbe.cs" $probe
    $routeSource = [IO.File]::ReadAllText("$probe/RouteProbe.cs").Replace(
        'internal sealed class RouteProbe', 'internal sealed partial class RouteProbe').Replace(
        'Compare(index, _nativeTerminal ?? Native());',
        'Compare(index, ObserveActionReturn(index));').Replace(
        'var benchmark = _matched > 0 ? Benchmark() : null;',
        'var benchmark = _matched > 0 ? Benchmark() : null; FinishTerminal(nativeStatus, complete);')
    [IO.File]::WriteAllText("$probe/RouteProbe.cs",$routeSource)
    Instrument '        _finish = () => { route.CaptureTerminal(); return ledger.Capture(combat, ended: true); };' @'
        using var lifecycle = route.InstallLifecycle();
        _finish = () => { route.CaptureTerminal(); return ledger.Capture(combat, ended: true); };
'@
    Instrument '            selector.Begin(i + 1, selected?.Id);' '            route.BeforeAction(i + 1);
            selector.Begin(i + 1, selected?.Id);'
}
if ($TargetedSearch) {
    Copy-Item "$PSScriptRoot/../m1-q5/TargetedSearch.cs" $probe
    Copy-Item "$PSScriptRoot/../m1-q4/RiskAudit.cs" $probe
    $routeSource = [IO.File]::ReadAllText("$probe/RouteProbe.cs").Replace(
        'var benchmark = _matched > 0 ? Benchmark() : null; FinishTerminal(nativeStatus, complete);',
        'FinishTerminal(nativeStatus, complete); var benchmark = (object?)null;')
    [IO.File]::WriteAllText("$probe/RouteProbe.cs",$routeSource)
    Instrument 'private sealed record Enemy' 'internal sealed record Enemy'
    Instrument 'private sealed record Move' 'internal sealed record Move'
    Instrument 'private sealed record Observation' 'internal sealed record Observation'
    Instrument 'private static Observation Observe' 'internal static Observation Observe'
    Instrument 'private static Move? Decide' 'internal static Move? Decide'
    Instrument '        using var lifecycle = route.InstallLifecycle();' '        using var lifecycle = route.InstallLifecycle();
        var risk = new RiskAudit(combat, player);
        risk.Install();'
    Instrument '            var expected = route.Inputs[i].Selected;' '            var expected = route.Inputs[i].Selected;
            if (!route.VerifyPublic(i, visible)) { status = "public_mapping_difference"; break; }'
    Instrument '            route.BeforeAction(i + 1);' '            route.BeforeAction(i + 1);
            risk.Step = i + 1;'
    Instrument '            if (!selector.Requested && status != "execution_timeout" && !route.Compare(i + 1)) break;' '            if (!selector.Requested && status != "execution_timeout"
                && (!route.Compare(i + 1) || !route.VerifyGenerated(i))) break;'
    Instrument '        route.Finish(status);' '        route.Finish(status);
        route.RunTargetedSearch();
        File.WriteAllText(Path.Combine(output, "risk.json"), JsonSerializer.Serialize(risk.Events, UnattendedTestFiles.JsonOptions));'
}
if ($CrossMechanism) {
    Copy-Item "$PSScriptRoot/../m1-q6/CrossMechanism.cs" $probe
    $searchSource = [IO.File]::ReadAllText("$probe/TargetedSearch.cs").Replace(
        'private const int PrefixLength = 18;',
        'private static int PrefixLength => Environment.GetEnvironmentVariable("M1Q6_CASE") == "regent" ? 8 : 18;').Replace(
        '_combat.Enemies.SelectMany(e => e.Powers.Select(p =>',
        '_combat.Enemies.Where(e => e.CurrentHp > 0 && e.IsHittable).SelectMany(e => e.Powers.Select(p =>')
    [IO.File]::WriteAllText("$probe/TargetedSearch.cs",$searchSource)
    Instrument '        route.RunTargetedSearch();' '        route.RunCrossMechanism();'
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
