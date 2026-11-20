using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Entities.Cards;

namespace CombatSolver;

internal sealed partial class CombatBeamSolver
{
    private bool _interactiveCapture;

    internal InteractiveCombat OpenInteractiveCombat(SimulationSnapshot seed) => new(this, seed);

    // The host owns the stable seed. This session owns every subsequent snapshot.
    internal sealed class InteractiveCombat(CombatBeamSolver solver, SimulationSnapshot seed) : IDisposable
    {
        private SimulationSnapshot? _current = seed;
        private ExecutionChoiceReplayCheckpoint? _checkpoint;
        private PlanAction? _plan;
        private TurnStartChoiceRequest? _request;
        private int _startTurn;
        private readonly List<string> _automatic = [];
        internal IReadOnlyList<string> Automatic => _automatic;
        internal SimulationSnapshot Current => _current ?? throw new ObjectDisposedException(nameof(InteractiveCombat));
        internal bool Waiting => _request != null;

        internal CardChoiceSpec Choice => _request?.Spec
            ?? throw new InvalidOperationException("No captured public choice");
        internal PlanChoiceTiming Timing => _request!.Timing;
        internal PlanAction? LastCompletedAction { get; private set; }

        internal void Play(PlanAction action)
        {
            if (Waiting || Current.BoundaryReason != SearchBoundaryReason.None || Current.TerminalStamp != null)
                throw new InvalidOperationException("Expected a stable player decision");
            _startTurn = Current.Turn;
            _plan = action;
            LastCompletedAction = null;
            _automatic.Clear();
            solver._interactiveCapture = true;
            try
            {
                Install(solver.Replay([action], Current, Current.Turn));
                ResolveAutomaticChoices();
            }
            finally { solver._interactiveCapture = false; }
        }

        internal void Select(IReadOnlyList<int> indices)
        {
            _automatic.Clear();
            solver._interactiveCapture = true;
            try
            {
                Resume(indices);
                ResolveAutomaticChoices();
            }
            finally { solver._interactiveCapture = false; }
        }

        private void ResolveAutomaticChoices()
        {
            while (Waiting && Choice.IsImplicitAllSelection)
            {
                if (_automatic.Count >= 64)
                    throw new NotSupportedException("Automatic choice limit");
                _automatic.Add(Choice.Effect.ToString());
                Resume(Enumerable.Range(0, Choice.Options.Count).ToArray());
            }
        }

        private void Resume(IReadOnlyList<int> indices)
        {
            var request = _request ?? throw new InvalidOperationException("No pending action");
            var spec = Choice;
            if (indices.Count < spec.MinCount || indices.Count > spec.MaxCount ||
                indices.Distinct().Count() != indices.Count || indices.Any(i => i < 0 || i >= spec.Options.Count))
                throw new ArgumentException("Selection does not match the active choice");
            var tokens = indices.Select(i =>
            {
                var card = spec.Options[i];
                string key = CardChoiceSupport.ChoiceCardKey(card);
                int sourceIndex = spec.SourceCards.ToList().FindIndex(c => ReferenceEquals(c.Original, card.Original));
                if (sourceIndex < 0)
                    throw new NotSupportedException("Candidate is missing from its source");
                int Occurrences(IEnumerable<PredictedCard> cards) =>
                    cards.Count(c => CardChoiceSupport.ChoiceCardKey(c) == key);
                return new PlanCardToken(card.Preview.Id.Entry, card.Preview.CurrentUpgradeLevel, key,
                    Occurrences(spec.SourceCards.Take(sourceIndex)), Occurrences(spec.Options.Take(i)), card.Preview.Title);
            }).ToArray();
            var choice = new PlanCardChoice(spec.Effect, spec.SourcePile, tokens,
                request.SourceId, request.ContextId, request.Timing);
            var plan = _plan!;
            bool turn = plan.Kind == PlanActionKind.EndTurn || Current.Turn > _startTurn
                || request.Timing != PlanChoiceTiming.Action;
            _plan = turn ? plan with { TurnStartChoices = [.. plan.TurnStartChoices ?? [], choice] }
                : plan.Choice == null && request.SourceId.Length == 0 ? plan with { Choice = choice }
                : plan with { NestedChoices = [.. plan.NestedChoices ?? [], choice],
                    NestedChoicesBeforePrimary = plan.NestedChoicesBeforePrimary + (plan.Choice == null ? 1 : 0) };
            var checkpoint = _checkpoint!;
            Install(solver.ResumeExecutionChoice(checkpoint, null, _plan));
        }

        private void Install(SimulationSnapshot next)
        {
            _checkpoint?.Dispose();
            if (!ReferenceEquals(Current, seed)) Current.ReleaseSimulator();
            _current = next;
            _checkpoint = null;
            _request = null;
            if (next.BoundaryReason == SearchBoundaryReason.None)
            {
                LastCompletedAction = _plan;
                _plan = null;
                return;
            }
            if (next.BoundaryReason != SearchBoundaryReason.PendingChoice) return;
            var combat = (SimulatedCombatState)next.Simulator.State.CombatState;
            var pending = combat.PendingTurnStartChoice;
            if (pending?.Spec is not { } spec || spec.SourcePile == PileType.Draw
                || spec.Effect == PlanChoiceEffect.ModDefined)
                return;
            // Draw-pile selectors can expose hidden order. Admit them only after a
            // native visibility contract identifies exactly which candidates are revealed.
            _checkpoint = solver.TakeExecutionChoiceCheckpoint(null, _plan, next);
            if (_checkpoint != null) _request = pending;
        }

        public void Dispose()
        {
            _checkpoint?.Dispose();
            _checkpoint = null;
            if (_current != null && !ReferenceEquals(_current, seed)) _current.ReleaseSimulator();
            _request = null;
            _current = null;
            _plan = null;
        }
    }
}
