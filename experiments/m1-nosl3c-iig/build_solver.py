"""Isolate the public reveal descriptor and pending checkpoint diagnostics."""
from hashlib import sha256
import json
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IID = runpy.run_path(str(HERE.parent / "m1-nosl3c-iid/build_solver.py"))
BASE = IID["BASE"]
VERSION = "0.51.5-iig.1"


def edit(path, old, new):
    code = path.read_text(encoding="utf-8")
    if code.count(old) != 1:
        raise ValueError(f"Unexpected anchor in {path.name}: {old}")
    path.write_text(code.replace(old,new),encoding="utf-8")


def stage(command, **kwargs):
    source = Path(command[2]).parent / "src/Search"
    bridge = source / "CombatBeamSolver.InteractiveCombat.cs"
    edit(source/"CardChoiceSupport.cs", "    bool PreserveOrderedRoutingResidues = false);", '''    bool PreserveOrderedRoutingResidues = false)
{
    // Set by the native-compatible reveal operation, never inferred from the pile.
    internal bool PublicReveal { get; init; }
}''')
    edit(source/"CardChoiceSupport.cs", """            contextId);
    }

    // A completed selection""", """            contextId) { PublicReveal = true };
    }

    // A completed selection""")
    edit(bridge, "        internal bool Waiting => _request != null;", """        internal bool Waiting => _request != null;
        internal object? InteractionTrace { get; private set; }

        private void TraceInteraction(string reason, TurnStartChoiceRequest? pending, bool captured)
        {
            InteractionTrace = new
            {
                reason, captured, source = pending?.SourcePile.ToString(), effect = pending?.Effect.ToString(),
                timing = pending?.Timing.ToString(), candidates = pending?.Spec?.Options.Count,
                boundary = Current.BoundaryReason.ToString(), action = _plan,
                gap_keys = Current.PredictionGaps.Select(g => g.Key + ": " + g.Reason).ToArray(),
            };
        }""")
    edit(bridge, "            _request = null;\n            if (next.BoundaryReason",
         "            _request = null;\n            InteractionTrace = null;\n            if (next.BoundaryReason")
    edit(bridge, """            if (pending?.Spec is not { } spec || spec.SourcePile == PileType.Draw
                || spec.Effect == PlanChoiceEffect.ModDefined)
                return;
            // Draw-pile selectors can expose hidden order. Admit them only after a
            // native visibility contract identifies exactly which candidates are revealed.
            _checkpoint = solver.TakeExecutionChoiceCheckpoint(null, _plan, next);
            if (_checkpoint != null) _request = pending;""",
         """            if (pending?.Spec is not { } spec)
            {
                TraceInteraction("request_or_spec_missing", pending, false);
                return;
            }
            if (spec.Effect == PlanChoiceEffect.ModDefined)
            {
                TraceInteraction("mod_defined_binding", pending, false);
                return;
            }
            _checkpoint = solver.TakeExecutionChoiceCheckpoint(null, _plan, next);
            if (spec.SourcePile == PileType.Draw && !spec.PublicReveal)
            {
                TraceInteraction("visibility_unverified", pending, _checkpoint != null);
                _checkpoint?.Dispose();
                _checkpoint = null;
                return;
            }
            if (spec.SourcePile == PileType.Draw && spec.Options.Any(option =>
                spec.SourceCards.Count(source => CardChoiceSupport.ChoiceCardKey(source) ==
                    CardChoiceSupport.ChoiceCardKey(option)) > 1))
            {
                TraceInteraction("ambiguous_draw_instances", pending, _checkpoint != null);
                _checkpoint?.Dispose();
                _checkpoint = null;
                return;
            }
            TraceInteraction(_checkpoint != null ? "published" : "checkpoint_unavailable", pending, _checkpoint != null);
            if (_checkpoint != null) _request = pending;""")
    edit(source/"CardChoiceSupport.cs", "    private const double SelfClearingRemovalPenalty", """    [ThreadStatic]
    internal static bool PublishingInteractiveChoices;

    private const double SelfClearingRemovalPenalty""")
    edit(source/"CardChoiceSupport.cs",
         "        simulator.History.RecordRisk(PredictionRiskReason.UnresolvedPlayerChoice);",
         """        if (!PublishingInteractiveChoices)
            simulator.History.RecordRisk(PredictionRiskReason.UnresolvedPlayerChoice);""")
    edit(source/"CardChoiceSupport.cs",
         "        List<PredictedCard> options = owner.DrawPile.Cards.Where(sampled.Contains).ToList();",
         """        // Native FromCombatPile filters the pile by sampled identity, then
        // presents draw candidates by rarity and card order. Search plans retain
        // their historical filtered-pile context.
        IEnumerable<PredictedCard> revealed = owner.DrawPile.Cards.Where(sampled.Contains);
        List<PredictedCard> options = PublishingInteractiveChoices
            ? revealed.OrderBy(card => card.Preview.Rarity).ThenBy(card => card,
                Comparer<PredictedCard>.Create((a, b) => CombatCardOrdering.Compare(simulator, a, b))).ToList()
            : revealed.ToList();""")
    code = bridge.read_text(encoding="utf-8")
    code = code.replace("            solver._interactiveCapture = true;",
        """            solver._interactiveCapture = true;
            bool previous = CardChoiceSupport.PublishingInteractiveChoices;
            CardChoiceSupport.PublishingInteractiveChoices = true;""")
    code = code.replace("            finally { solver._interactiveCapture = false; }",
        """            finally
            {
                CardChoiceSupport.PublishingInteractiveChoices = previous;
                solver._interactiveCapture = false;
            }""")
    bridge.write_text(code, encoding="utf-8")
    IID["stage"](command, **kwargs)
    manifest = {p.name:sha256(p.read_bytes()).hexdigest() for p in (bridge,source/"CardChoiceSupport.cs")}
    (Path(command[-1]).parent/"interaction-sources.json").write_text(json.dumps(manifest,indent=2)+"\n")


if __name__ == "__main__":
    f = BASE["main"]
    FunctionType(f.__code__,f.__globals__|dict(VERSION=VERSION,subprocess=SimpleNamespace(run=stage)))()
