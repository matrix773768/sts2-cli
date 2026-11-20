using CombatSolver.Engine.InCombat.Simulation;
using System.Reflection;
using System.Text.Json;
using CombatSolver;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    private object? _interactive;
    private int _decisionPosition;
    private string? _interactiveStop;
    private string? _interactiveDetail;
    private readonly List<int> _selection = [];

    internal void OpenInteractive(CombatBeamSolver solver)
    {
        _interactive = solver.GetType().GetMethod("OpenInteractiveCombat",
            BindingFlags.Instance | BindingFlags.NonPublic)!.Invoke(solver, [_root.State]);
    }

    private T InteractiveProperty<T>(string name) => (T)_interactive!.GetType()
        .GetProperty(name, BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(_interactive)!;

    private void InteractiveInvoke(string name, object parameter) => _interactive!.GetType()
        .GetMethod(name, BindingFlags.Instance | BindingFlags.NonPublic)!.Invoke(_interactive, [parameter]);

    private static string StatusOf(SimulationSnapshot snapshot) =>
        snapshot.HasRisk || snapshot.BoundaryReason != SearchBoundaryReason.None ? "unsupported" :
        snapshot.TerminalStamp == null ? "active" : snapshot.PlayerDead ? "death" :
        snapshot.AllEnemiesDead ? "predicted_win" : "unsupported";

    internal object InteractiveView()
    {
        var snapshot = InteractiveProperty<SimulationSnapshot>("Current");
        var waiting = InteractiveProperty<bool>("Waiting");
        string status = _interactiveStop ?? (waiting && !snapshot.HasRisk ? "active" : StatusOf(snapshot));
        object? observation = null;
        try
        {
            if (status == "active" && waiting)
            {
                var spec = InteractiveProperty<CardChoiceSpec>("Choice");
                var candidates = spec.Options.Select((c, i) => NoslInstance(c, i)).ToArray();
                var actions = new List<NoslAction>();
                if (_selection.Count < spec.MaxCount)
                    foreach (var card in candidates)
                        if (!_selection.Contains(card.Index))
                            actions.Add(new(actions.Count, "select_candidate", Choice: card.Index));
                if (_selection.Count >= spec.MinCount)
                    actions.Add(new(actions.Count, "confirm_selection"));
                if (actions.Count == 0)
                    throw new NotSupportedException("Captured selector has no legal response");
                observation = ObserveNosl(_root, snapshot, actions, new
                {
                    phase = "choice", effect = spec.Effect.ToString(), pile = spec.SourcePile.ToString(),
                    timing = InteractiveProperty<PlanChoiceTiming>("Timing").ToString(),
                    min = spec.MinCount, max = spec.MaxCount, candidates, selected = _selection.ToArray(),
                });
                _selectionMenu = actions;
            }
            else if (status == "active")
                observation = ObserveNosl(_root, snapshot);
        }
        catch (NotSupportedException error)
        {
            status = _interactiveStop = "unsupported";
            _interactiveDetail = error.Message;
        }
        var sim = snapshot.Simulator;
        var combat = (SimulatedCombatState)sim.State.CombatState;
        var potions = Enumerable.Range(0, _player.PotionSlots.Count)
            .Select(i => combat.GetPotionAtSlot(_player, i)?.Id.Entry).ToArray();
        if (status != "active" && Digest(_root.State!) != _root.Frame.Stamp)
            throw new InvalidOperationException("Interactive episode changed its stable source");
        return new
        {
            status, observation, automatic = InteractiveProperty<IReadOnlyList<string>>("Automatic"), actions = _decisionPosition, transitions = _used,
            detail = _interactiveDetail ?? (status == "unsupported" ? snapshot.BoundaryReason.ToString() : null),
            audit_action = InteractiveProperty<PlanAction?>("LastCompletedAction"),
            audit_stamp = waiting ? null : Digest(snapshot),
            terminal_observation = status == "active" ? null : new
            {
                turn = snapshot.Turn, hp = snapshot.PlayerHp, max_hp = snapshot.PlayerMaxHp,
                block = snapshot.PlayerBlock, energy = snapshot.Energy, potions,
            },
            result = status == "active" ? null : new
            {
                hp = snapshot.PlayerHp, cumulative_loss = snapshot.CumulativePlayerHpLost,
                boundary = snapshot.BoundaryReason.ToString(), gold = combat.GetPlayerGold(_player),
                gaps = snapshot.PredictionGaps.Select(g => g.Key).ToArray(),
            },
        };
    }

    private List<NoslAction>? _selectionMenu;
    internal object InteractiveStep(JsonElement request)
    {
        if (_interactiveStop != null || request.GetProperty("position").GetInt32() != _decisionPosition)
            return InvalidAction("Stale or unavailable decision");
        int index = request.GetProperty("index").GetInt32();
        bool waiting = InteractiveProperty<bool>("Waiting");
        if (!waiting && StatusOf(InteractiveProperty<SimulationSnapshot>("Current")) != "active")
            return InvalidAction("No active decision");
        if (index < 0 || index >= (waiting ? _selectionMenu?.Count : _episodeMenu?.Length))
            return InvalidAction("Index outside the current legal menu");
        if (_decisionPosition >= _cap)
        {
            _interactiveStop = "truncated";
            _interactiveDetail = "action_cap";
            return InteractiveView();
        }
        try
        {
            if (!waiting)
            {
                _used++;
                InteractiveInvoke("Play", _episodeMenu![index].Action);
            }
            else if (_selectionMenu![index].Choice is int candidate)
                _selection.Add(candidate);
            else
            {
                _used++;
                InteractiveInvoke("Select", _selection.ToArray());
                _selection.Clear();
            }
            _decisionPosition++;
        }
        catch (TargetInvocationException error)
        {
            _interactiveStop = error.InnerException is NotSupportedException ? "unsupported" : "error";
            _interactiveDetail = error.InnerException?.Message ?? error.Message;
        }
        return InteractiveView();
    }

    private void CloseInteractive()
    {
        (_interactive as IDisposable)?.Dispose();
        _interactive = null;
    }
}
