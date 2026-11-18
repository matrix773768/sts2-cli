"""Build an F2-only host from the frozen F1, Q1, Q3 and I1 sources."""
import importlib.util
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("f1_build", HERE.parent / "m1-f1/build.py")
f1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f1)
replace = f1.replace


def stage(src):
    f1.stage(src)
    for name in ("ChoiceAudit.cs", "TeacherChoice.cs"):
        shutil.copyfile(HERE / name, src / name)
    replace(src / "ChoiceScope.cs", 'string action, Dictionary<string, object?> args)\n    {',
            '''string action, Dictionary<string, object?> args) =>
        WithF2Selector(player, choices, () => ExecuteAction(action, args));

    private Dictionary<string, object?> WithF2Selector(Player player, ICardSelector choices,
        Func<Dictionary<string, object?>> execute)
    {''')
    replace(src / "ChoiceScope.cs", 'return ExecuteAction(action, args);', 'return execute();')
    choices = src / "CombatChoices.cs"
    replace(choices, '["HEADBUTT"] = new("discard", "topdeck", 1, false),',
            '["HEADBUTT"] = new("discard", "topdeck", 1, false),\n'
            '        ["SURVIVOR"] = new("hand", "discard", 1, false),\n'
            '        ["PREPARED"] = new("hand", "discard", 1, true),')
    replace(choices, '        _minionStrikes = pcs.Hand',
            '        if (contract.Effect == "discard")\n'
            '            _discard = DiscardAudit.Capture(combat, cards, _selected, minSelect, maxSelect);\n'
            '        _minionStrikes = pcs.Hand')
    replace(choices, '    private int _minionStrikes;', '    private int _minionStrikes;\n    private DiscardAudit? _discard;')
    replace(choices, '        _contract = null;', '        _contract = null;\n        _discard = null;')
    replace(choices, '                "exhaust" =>', '                "discard" => _discard!.Verify(combat, StateChecks, _step, _action!),\n'
            '                "exhaust" =>')
    replace(choices, 'bool legal = minSelect >= 0', 'bool legal = (contract.Effect != "discard" || minSelect == maxSelect) && minSelect >= 0')
    replace(choices, '    private bool _active;', '    internal int ExpectedDiscardCount { get; set; }\n    private bool _active;')
    replace(choices, 'minSelect == maxSelect) && minSelect',
            'minSelect == maxSelect && minSelect == Math.Min(ExpectedDiscardCount, cards.Length)) && minSelect')

    real = src / "RealCombat.cs"
    replace(real, '            case "f1_step":', '''            case "f1_audit":
                return new() { ["type"] = "f2_audit",
                    ["stamp"] = Hash(ContinuationStamp.CaptureLive(_combat!).StateText),
                    ["rng"] = DiscardAudit.Rng(_combat!) };
            case "f1_unpatch_neutralize":
                var method = AccessTools.DeclaredMethod(typeof(MegaCrit.Sts2.Core.Models.Cards.Neutralize), "OnPlay");
                const string owner = "sts2headless.locpatch";
                var prefix = Harmony.GetPatchInfo(method)?.Prefixes.SingleOrDefault(p =>
                    p.owner == owner && p.PatchMethod.Name == "NeutralizePrefix");
                if (prefix == null) throw new InvalidOperationException("Missing expected Neutralize prefix");
                new Harmony("m1-f2.native-neutralize").Unpatch(method, prefix.PatchMethod);
                return new() { ["type"] = "f2_unpatched", ["method"] = prefix.PatchMethod.Name };
            case "f1_step":''')
    replace(real, 'var choices = _choices!;', '''var choices = request.TryGetProperty("hand_order_discard", out _) ?
            (_choices = new CombatChoices(player, false, combat, false)) : _choices!;
        if (selected?.Id is "PREPARED" or "SURVIVOR")
            choices.ExpectedDiscardCount = selected.Id == "SURVIVOR" ? 1 :
                pcs.Hand.Cards[selected.HandIndex].DynamicVars.Cards.IntValue;
        var pre = AuditState(combat, request);''')
    replace(real, '["choice_failure"] = choices.Failure,', '''["choice_failure"] = choices.Failure,
            ["pre_audit"] = pre,
            ["post_audit"] = AuditState(combat, request),
            ["choice_requests"] = choices.Log.ToArray(),
            ["choice_checks"] = choices.StateChecks.ToArray(),''')
    # Return only the action's transactions, while retaining the original final ledger.
    replace(real, '        var pre = AuditState', '        int requestStart = choices.Log.Count, checkStart = choices.StateChecks.Count;\n        var pre = AuditState')
    replace(real, '["choice_requests"] = choices.Log.ToArray(),', '["choice_requests"] = choices.Log.Skip(requestStart).ToArray(),')
    replace(real, '["choice_checks"] = choices.StateChecks.ToArray(),', '["choice_checks"] = choices.StateChecks.Skip(checkStart).ToArray(),')
    replace(real, '    private static int? TargetIndex', '''    private static object? AuditState(CombatState combat, JsonElement request) =>
        request.TryGetProperty("audit", out _) && CombatManager.Instance.IsInProgress
            && combat.Players.Single().Creature.CurrentHp > 0
        ? new { stamp = Hash(ContinuationStamp.CaptureLive(combat).StateText), rng = DiscardAudit.Rng(combat) }
        : null;

    private static int? TargetIndex''')
    teacher = src / "IntegrationProbe.cs"
    replace(teacher, 'internal static class IntegrationProbe', 'internal static partial class IntegrationProbe')
    source = teacher.read_text(encoding="utf-8")
    a = source.index('        if (actions.Any(action =>')
    b = source.index('        if (!result.Snapshot.AllEnemiesDead', a)
    source = source[:a] + '''        if (actions.FirstOrDefault(action => !TeacherChoice.Supports(action)) is { } rejectedAction)
        {
            response["rejected_action"] = new
            {
                kind = rejectedAction.Kind.ToString(), rejectedAction.CardId, rejectedAction.PotionId,
                rejectedAction.TargetCombatId, rejectedAction.PotionSlot,
                effect = rejectedAction.Choice?.Effect.ToString(), pile = rejectedAction.Choice?.SourcePile.ToString(),
                timing = rejectedAction.Choice?.Timing.ToString(),
                count = rejectedAction.Choice?.Cards.Count, source = rejectedAction.Choice?.SourceId,
                context = rejectedAction.Choice?.ContextId,
            };
            return Stop("unsupported", "plan_action_or_choice");
        }
''' + source[b:]
    teacher.write_text(source, encoding="utf-8")
    replace(teacher, '        SolverResult result;\n        try { result = solver.Solve(); }',
            '''        bool fixedRoute = cmd.TryGetProperty("fixed_actions", out var recorded);
        SolverResult? result = null;
        try { if (!fixedRoute) result = solver.Solve(); }''')
    replace(teacher, '        var actions = result.BestNode.Actions;',
            '''        var options = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
        options.Converters.Add(new System.Text.Json.Serialization.JsonStringEnumConverter());
        IReadOnlyList<PlanAction> actions = fixedRoute
            ? recorded.Deserialize<PlanAction[]>(options)!
            : result!.BestNode.Actions;''')
    replace(teacher, '["predicted_win"] = result.Snapshot.AllEnemiesDead && !result.Snapshot.PlayerDead,',
            '["predicted_win"] = result?.Snapshot is { AllEnemiesDead: true, PlayerDead: false }, ["fixed_route"] = fixedRoute,')
    replace(teacher, 'result.TransitionCount, ["expanded_nodes"] = result.ExpandedNodes,',
            'result?.TransitionCount, ["expanded_nodes"] = result?.ExpandedNodes,')
    replace(teacher, 'result.TotalExpandedNodes, ["boundary"] = result.BoundaryReason.ToString(),',
            'result?.TotalExpandedNodes, ["boundary"] = result?.BoundaryReason.ToString(),')
    replace(teacher, '        if (!result.Snapshot.AllEnemiesDead || result.Snapshot.PlayerDead)',
            '        if (result != null && (!result.Snapshot.AllEnemiesDead || result.Snapshot.PlayerDead))')
    replace(teacher, '        response["root"] = initial;', '        response["predicted_win"] = true;\n        response["root"] = initial;')
    replace(teacher, '                string nativeAction;', '''                if (HasChoice(action, "nested_choices") || HasChoice(action, "turn_start_choices"))
                    return Rejected("Unsupported nested or turn-start choice");
                var choice = TeacherChoice.Bind(action, player);
                string nativeAction;''')
    replace(teacher, '                if (kind == "UsePotion")\n                {',
            '''                if (kind == "UsePotion" && action.GetProperty("potion_id").GetString() == "COLORLESS_POTION")
                {
                    nativeAction = "use_potion";
                    int slot = action.GetProperty("potion_slot").GetInt32();
                    args["potion_slot"] = slot;
                    decision = sim.UseF2ColorlessPotion(player, slot, choice!);
                }
                else if (kind == "UsePotion")
                {''')
    replace(teacher, '                    decision = sim.ExecuteAction(nativeAction, args);',
            '''                    decision = choice == null ? sim.ExecuteAction(nativeAction, args) :
                        sim.ExecuteF1Action(player, choice, nativeAction, args);''')
    replace(teacher, '                return new() { ["type"] = "i1_state", ["state"] = _terminal ?? _nativeCapture(),',
            '''                var choiceEvidence = choice?.Verify();
                return new() { ["type"] = "i1_state", ["state"] = _terminal ?? _nativeCapture(),
                    ["choice_evidence"] = choiceEvidence,''')


if __name__ == "__main__":
    f1.i1.build(f1.i1.ROOT / "logs/m1-f2-build", stage)
