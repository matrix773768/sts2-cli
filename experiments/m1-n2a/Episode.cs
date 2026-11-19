using System.Collections.Immutable;
using System.Diagnostics;
using System.Text.Json;
using CombatSolver;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Entities.Cards;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    private sealed record PublicEnemy(int Index, int Hp, int Block);
    private sealed record PublicCard(int Index, string Id, int Upgrade);
    private sealed record PublicAction(int Index, int? Card, int? Target, int? Cost);
    private sealed record Observation(int Turn, int Hp, int Block, int Energy, int DrawCount,
        ImmutableArray<PublicCard> Hand, ImmutableArray<PublicEnemy> Enemies, ImmutableArray<PublicAction> Actions);

    private Node? _episodeNode;
    private Option[]? _episodeMenu;
    private string? _episodeStatus, _episodeDetail;
    private double _episodeObserveMs, _episodeReplayMs;

    internal object EpisodeView()
    {
        var node = _episodeNode ??= _root;
        Observation? observation = null;
        if (_episodeStatus == null && node.Frame.Stop == "active")
        {
            long begin = Stopwatch.GetTimestamp();
            try { observation = ObserveEpisode(node); }
            catch (NotSupportedException error)
            {
                _episodeStatus = "unsupported";
                _episodeDetail = error.Message;
            }
            finally { _episodeObserveMs += Stopwatch.GetElapsedTime(begin).TotalMilliseconds; }
        }
        string status = _episodeStatus ?? node.Frame.Stop;
        if (status != "active" && Digest(_root.State!) != _root.Frame.Stamp)
            throw new InvalidOperationException("Episode changed its source snapshot");
        return new
        {
            status, observation, detail = _episodeDetail,
            transitions = _used, actions = node.Depth,
            observe_ms = _episodeObserveMs, replay_ms = _replayMs,
            advance_ms = _episodeReplayMs,
            result = status == "active" ? null : new
            {
                node.Frame.Hp, node.Frame.CumulativeLoss, node.Frame.Boundary,
                node.Frame.Potions, node.Frame.Energy, node.Frame.MaxHp, node.Frame.Gold,
                node.Frame.Gaps, evidence = "prediction_only",
            },
        };
    }

    private Observation ObserveEpisode(Node node)
    {
        var snapshot = node.State!;
        var sim = (CombatPredictionSimulator)snapshot.Simulator;
        var combat = (SimulatedCombatState)sim.State.CombatState;
        var pc = sim.State.GetPlayerCombatState(_player);
        var targets = combat.KnownEnemies.Where(e => sim.State.GetCreature(e).IsAlive).ToArray();
        if (targets.Any(e => !sim.State.IsHittable(e)))
            throw new NotSupportedException("Alive enemy without qualified target mapping");

        var moves = new List<Option>();
        var actions = ImmutableArray.CreateBuilder<PublicAction>();
        for (int index = 0; index < pc.Hand.Cards.Count; index++)
        {
            var card = pc.Hand.Cards[index];
            if (!combat.CanPlayCard(sim, card)) continue;
            var type = sim.GetTargetType(card);
            if (type is not (TargetType.AnyEnemy or TargetType.Self or TargetType.None or
                TargetType.AllEnemies or TargetType.RandomEnemy or TargetType.TargetedNoCreature))
                throw new NotSupportedException($"Unqualified target type: {type}");
            var key = CardChoiceSupport.ChoiceCardKey(card);
            var previous = pc.Hand.Cards.Take(index);
            var cardId = card.Preview.Id.Entry;
            int cost = card.GetEnergyCostWithModifiers(sim, pc);
            for (int target = 0; target < (type == TargetType.AnyEnemy ? targets.Length : 1); target++)
            {
                int? targetIndex = type == TargetType.AnyEnemy ? target : null;
                uint? combatId = targetIndex is int t ? targets[t].CombatId : null;
                actions.Add(new(actions.Count, index, targetIndex, cost));
                moves.Add(new(new PlanAction(PlanActionKind.PlayCard, snapshot.Turn,
                    CardId: cardId, CardOccurrence: previous.Count(c => c.Preview.Id.Entry == cardId),
                    TargetCombatId: combatId, CardStateKey: key,
                    CardStateOccurrence: previous.Count(c => CardChoiceSupport.ChoiceCardKey(c) == key)), null));
            }
        }
        actions.Add(new(actions.Count, null, null, null));
        moves.Add(new(new PlanAction(PlanActionKind.EndTurn, snapshot.Turn), null));
        _episodeMenu = moves.ToArray();
        return new(snapshot.Turn, snapshot.PlayerHp, snapshot.PlayerBlock, snapshot.Energy,
            pc.DrawPile.Cards.Count,
            pc.Hand.Cards.Select((c, i) => new PublicCard(i, c.Preview.Id.Entry, c.Preview.CurrentUpgradeLevel))
                .ToImmutableArray(),
            targets.Select((e, i) => new PublicEnemy(i, sim.State.GetCreature(e).CurrentHp,
                sim.State.GetCreature(e).Block)).ToImmutableArray(),
            actions.ToImmutable());
    }

    internal object EpisodeStep(JsonElement request)
    {
        var current = _episodeNode;
        if (current == null || _episodeStatus != null || current.Frame.Stop != "active" || _episodeMenu == null)
            throw new InvalidOperationException("Episode has no active legal menu");
        if (request.GetProperty("position").GetInt32() != current.Depth)
            throw new ArgumentException("Stale action position");
        int index = request.GetProperty("index").GetInt32();
        if (index < 0 || index >= _episodeMenu.Length)
            throw new ArgumentException("Action index outside current menu");
        long start = Stopwatch.GetTimestamp();
        _watch.Start();
        try
        {
            var next = Advance(current, _episodeMenu[index]);
            if (next == null)
            {
                _episodeStatus = "truncated";
                _episodeDetail = _limit;
            }
            else
            {
                _episodeNode = next;
                if (current != _root) Release(current);
                if (next.Depth >= _cap && next.Frame.Stop == "active")
                {
                    _episodeStatus = "truncated";
                    _episodeDetail = "action_cap";
                }
            }
        }
        catch (NotSupportedException error)
        {
            _episodeStatus = "unsupported";
            _episodeDetail = error.Message;
        }
        finally
        {
            _watch.Stop();
            _episodeReplayMs += Stopwatch.GetElapsedTime(start).TotalMilliseconds;
        }
        return EpisodeView();
    }
}
