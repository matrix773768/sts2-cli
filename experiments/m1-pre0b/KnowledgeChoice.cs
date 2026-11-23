using System.Reflection;
using CombatSolver;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Entities.Cards;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    private const BindingFlags PrivateInstance = BindingFlags.Instance | BindingFlags.NonPublic;
    private CombatBeamSolver? _pre0bSolver;

    private KnowledgeDemonChoiceRequest? KnowledgeChoice(SimulationSnapshot snapshot) =>
        snapshot.BoundaryReason == SearchBoundaryReason.PendingChoice && !snapshot.HasRisk
            ? ((SimulatedCombatState)snapshot.Simulator.State.CombatState).PendingKnowledgeDemonChoice
            : null;

    private void SubmitKnowledgeChoice(KnowledgeDemonChoiceRequest request, int index)
    {
        var type = _interactive!.GetType();
        var field = type.GetField("_plan", PrivateInstance)!;
        var plan = (PlanAction)field.GetValue(_interactive)!;
        var id = request.OptionIds[index];
        var choice = new PlanCardChoice(PlanChoiceEffect.ApplyKnowledgeCurse, PileType.None,
            [new PlanCardToken(id, 0, "", 0, 0, id)], request.SourceId, Timing: PlanChoiceTiming.EnemyTurn);
        field.SetValue(_interactive, plan with { TurnStartChoices = [.. plan.TurnStartChoices ?? [], choice] });

        var capture = typeof(CombatBeamSolver).GetField("_interactiveCapture", PrivateInstance)!;
        var previousCapture = capture.GetValue(_pre0bSolver);
        var publication = typeof(CardChoiceSupport).GetField("PublishingInteractiveChoices",
            BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)!;
        var previousPublication = publication.GetValue(null);
        try
        {
            capture.SetValue(_pre0bSolver, true);
            publication.SetValue(null, true);
            var resumed = type.GetMethod("ReplayChoice", PrivateInstance)!.Invoke(_interactive, null)!;
            InteractiveInvoke("Install", resumed);
            type.GetMethod("ResolveAutomaticChoices", PrivateInstance)!.Invoke(_interactive, null);
        }
        finally
        {
            publication.SetValue(null, previousPublication);
            capture.SetValue(_pre0bSolver, previousCapture);
        }
    }
}
