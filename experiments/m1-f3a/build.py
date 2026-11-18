"""Build the F2 isolated host with a fixed F3A budget ladder and profiling."""
import importlib.util
from pathlib import Path
from profiles import BUDGETS

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("f2_build", HERE.parent / "m1-f2/build.py")
f2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f2)

def stage(src):
    f2.stage(src)
    probe = src / "IntegrationProbe.cs"
    choices = src / "TeacherChoice.cs"
    f2.replace(choices, '                "BEETLE_JUICE" =>', '''                "DEXTERITY_POTION" or "FLEX_POTION" or "BLESSING_OF_THE_FORGE" =>
                    action.TargetCombatId == null && action.Choice == null,
                "BEETLE_JUICE" =>''')
    f2.replace(choices, 'UseF2ColorlessPotion(Player player, int slot, TeacherChoice selector)',
               'UseF3PlayerPotion(Player player, int slot, string id, TeacherChoice? selector)')
    f2.replace(choices, 'potion.Id.Entry != "COLORLESS_POTION"',
               'potion.Id.Entry != id || (id == "COLORLESS_POTION") != (selector != null)')
    f2.replace(choices, 'Unexpected colorless potion slot, target or play phase',
               'Unexpected player potion slot, target, selection or play phase')
    f2.replace(choices, '        return WithF2Selector(player, selector, () =>',
               '        Dictionary<string, object?> Use()')
    f2.replace(choices, '        });', '        }\n        return selector == null ? Use() : WithF2Selector(player, selector, Use);')
    f2.replace(choices, 'Native colorless potion action failed', 'Native player potion action failed')
    f2.replace(choices, 'Native colorless potion did not complete', 'Native player potion did not complete')
    f2.replace(choices, '    private CardModel? _selected;',
               '''    private CardModel? _selected;
    private CardModel? _implicitHeadbutt;''')
    f2.replace(choices, '        return new(player, choice);',
               '''        var selector = new TeacherChoice(player, choice);
        var token = choice.Cards.Single();
        if (source == "HEADBUTT" && token is { SourceOccurrence: 0, OptionOccurrence: 0 } &&
            player.PlayerCombatState!.DiscardPile.Cards is [var only] &&
            only.Id.Entry == token.CardId && only.CurrentUpgradeLevel == token.UpgradeLevel &&
            CardChoiceSupport.ChoiceCardKey(only) == token.StateKey)
            selector._implicitHeadbutt = only;
        return selector;''')
    f2.replace(choices, '        if (_failure != null || _selected == null || !destination.Any(c => ReferenceEquals(c, _selected)))',
               '''        if (_selected == null && _failure == null && _implicitHeadbutt is { } only &&
            destination.Any(c => ReferenceEquals(c, only)) &&
            !pcs.DiscardPile.Cards.Any(c => ReferenceEquals(c, only)))
            return new { binding = new { surface = "implicit_singleton", effect = "MoveToDrawTop",
                selected = contract.Cards.Single(), option = 0, source_index = 0 }, destination_verified = true };
        if (_failure != null || _selected == null || !destination.Any(c => ReferenceEquals(c, _selected)))''')
    f2.replace(probe, '                if (kind == "UsePotion" && action.GetProperty("potion_id").GetString() == "COLORLESS_POTION")',
               '''                string? potionId = kind == "UsePotion" ? action.GetProperty("potion_id").GetString() : null;
                if (potionId is "COLORLESS_POTION" or "DEXTERITY_POTION" or "FLEX_POTION" or "BLESSING_OF_THE_FORGE")''')
    f2.replace(probe, '                    decision = sim.UseF2ColorlessPotion(player, slot, choice!);',
               '''                    if (action.TryGetProperty("target_combat_id", out var explicitTarget) &&
                        explicitTarget.ValueKind != JsonValueKind.Null)
                        return Rejected("Player potion requires an implicit single-player target");
                    decision = sim.UseF3PlayerPotion(player, slot, potionId, choice);''')
    profiles = "\n".join(f"            {nodes} => ({soft}, {cancel})," for nodes, soft, cancel in BUDGETS)
    f2.replace(probe, '''        policy = policy with { Profile = new SolverSearchProfile(24, 1000, 32, 18, 24, 6000), MaxDegreeOfParallelism = 1 };
        using var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(8));''',
        '''        int nodes = cmd.TryGetProperty("node_budget", out var requestedNodes) ? requestedNodes.GetInt32() : 1000;
        (int softMs, int cancelMs) = nodes switch
        {
''' + profiles + '''
            _ => throw new ArgumentOutOfRangeException(nameof(nodes)),
        };
        policy = policy with { Profile = new SolverSearchProfile(24, nodes, 32, 18, 24, softMs), MaxDegreeOfParallelism = 1 };
        using var cancel = new CancellationTokenSource(TimeSpan.FromMilliseconds(cancelMs));''')
    f2.replace(probe, '        SolverResult? result = null;',
        '''        using var process = Process.GetCurrentProcess();
        var cpuStarted = process.TotalProcessorTime;
        long searchStarted = Stopwatch.GetTimestamp();
        SolverResult? result = null;''')
    f2.replace(probe, '["reason"] = "cancelled", ["solve_ms"] = watch.Elapsed.TotalMilliseconds',
        '''["reason"] = "cancelled", ["solve_ms"] = Stopwatch.GetElapsedTime(searchStarted).TotalMilliseconds,
                ["search_cpu_ms"] = (process.TotalProcessorTime - cpuStarted).TotalMilliseconds''')
    f2.replace(probe, 'double solveMs = watch.Elapsed.TotalMilliseconds;',
        '''double solveMs = Stopwatch.GetElapsedTime(searchStarted).TotalMilliseconds;
        double searchCpuMs = (process.TotalProcessorTime - cpuStarted).TotalMilliseconds;''')
    f2.replace(probe, '["solve_ms"] = solveMs,', '["solve_ms"] = solveMs, ["search_cpu_ms"] = searchCpuMs,')
    # A non-winning partial plan's execution shape cannot block budget escalation.
    original = probe.read_text(encoding="utf-8")
    start = original.index("        if (actions.FirstOrDefault")
    outcome = original.index("        if (result != null &&", start)
    limit = original.index("        if (actions.Count is", outcome)
    probe.write_text(original[:start] + original[outcome:limit] + original[start:outcome] +
                     original[limit:], encoding="utf-8")


if __name__ == "__main__":
    f2.f1.i1.build(f2.f1.i1.ROOT / "logs/m1-f3a-build", stage)
