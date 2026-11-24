using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using CombatSolver;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Entities.Cards;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    internal Dictionary<string, object?> TurnGraph(JsonElement request)
    {
        var session = (CombatBeamSolver.InteractiveCombat)_interactive!;
        var menu = _episodeMenu;
        try
        {
            return new TurnGraphRun(this, session.Current, request).Run(session.Waiting);
        }
        finally
        {
            _episodeMenu = menu;
        }
    }

    private sealed class TurnGraphRun(FirstWin owner, SimulationSnapshot seed, JsonElement request)
    {
        private sealed record Move(string Kind, int? Index = null, string? Card = null, uint? Target = null,
            int[]? Selection = null);
        private sealed record Edge(int From, int To, Move Action);
        private sealed record Outcome(string Kind, string? Reason, string State, object Public);
        private sealed class Vertex(int id, Edge? incoming, Outcome? outcome)
        {
            internal int Id { get; } = id;
            internal Edge? Incoming { get; } = incoming;
            internal Outcome? Outcome { get; } = outcome;
            internal List<Edge> Outgoing { get; } = [];
            internal HashSet<int> FirstActions { get; } = [];
            internal bool Expanding { get; set; }
        }

        private static readonly JsonSerializerOptions Wire = new()
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        };
        private readonly string _mode = request.GetProperty("mode").GetString()!;
        private readonly int _cap = request.GetProperty("transitions").GetInt32();
        private readonly int _wall = request.GetProperty("wall_ms").GetInt32();
        private readonly int _depth = request.GetProperty("depth").GetInt32();
        private readonly long _memory = request.GetProperty("memory_bytes").GetInt64();
        private readonly bool _oracle = Flag(request, "oracle");
        private readonly bool _verify = Flag(request, "verify");
        private readonly bool _potionsEnabled = Flag(request, "potions");
        private readonly Stopwatch _clock = Stopwatch.StartNew();
        private readonly Dictionary<string, Vertex> _cache = new(StringComparer.Ordinal);
        private readonly List<Vertex> _vertices = [];
        private readonly List<Edge> _edges = [];
        private string? _stop;
        private bool _identityRule;
        private int _transitions, _forks, _restoreCalls, _hits, _cycles, _choiceNodes, _maxMoves, _maxDepth;
        private long _menuTicks, _transferTicks, _forkTicks, _restoreTicks, _keyTicks, _lookupTicks;
        private long _peakManaged;

        private static bool Flag(JsonElement item, string key) =>
            item.TryGetProperty(key, out var value) && value.GetBoolean();
        private static double Ms(long ticks) => 1000.0 * ticks / Stopwatch.Frequency;
        private static string HashText(string text) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
        private static string Encode(object value) => JsonSerializer.Serialize(value, Wire);

        private bool CanNormalizeIdentities()
        {
            // Restrict the rule to native basic cards with no identity-sensitive listeners.
            var sim = seed.Simulator;
            var combat = (SimulatedCombatState)sim.State.CombatState;
            var pc = sim.State.GetPlayerCombatState(owner._player);
            var cards = pc.Hand.Cards.Concat(pc.DrawPile.Cards).Concat(pc.DiscardPile.Cards)
                .Concat(pc.ExhaustPile.Cards);
            return !_oracle && !_potionsEnabled && owner._player.Relics.Count == 0
                && combat.KnownEnemies.All(enemy => enemy.Monster?.Id.Entry is "CUBEX_CONSTRUCT" or "FUZZY_WURM_CRAWLER")
                && owner._player.Deck.Cards.All(card => card.Id.Entry is "STRIKE_IRONCLAD" or "DEFEND_IRONCLAD")
                && cards.All(card => card.Preview.Id.Entry is "STRIKE_IRONCLAD" or "DEFEND_IRONCLAD"
                    && card.Preview.Enchantment == null && card.Preview.Affliction == null && !card.Preview.IsDupe)
                && !combat.EffectivePowers().Any(power => power.Owner == owner._player.Creature)
                && owner._player.PotionSlots.All(potion => potion == null);
        }

        private string StateText(SimulationSnapshot state)
        {
            var combat = (SimulatedCombatState)state.Simulator.State.CombatState;
            var snapshot = ContinuationStamp.CapturePredicted(owner._player, state.Simulator,
                state.Turn, EmptyForecast, seed.Turn).StateText;
            return Encode(new
            {
                snapshot, side = combat.CurrentSide, combat.RoundNumber, state.BoundaryReason,
                state.HasRisk, state.PlayerDead, state.AllEnemiesDead, state.ShufflesCrossed,
                deaths = state.ProcessedEnemyDeaths.Order(), state.CumulativePlayerHpLost,
                state.RecoveredPlayerHp, state.DeathSaveRelicHpRestored, state.PotionUseCount,
                state.AutomaticPotionUseCount, state.HistoryEntryCount,
                gaps = state.PredictionGaps.Select(gap => gap.Key).Order(StringComparer.Ordinal),
            });
        }

        private object PublicState(SimulationSnapshot state)
        {
            var sim = state.Simulator;
            var player = owner._player;
            var combat = (SimulatedCombatState)sim.State.CombatState;
            var pc = sim.State.GetPlayerCombatState(player);
            return new
            {
                state.Turn, hp = state.PlayerHp, max_hp = state.PlayerMaxHp, block = state.PlayerBlock,
                state.Energy, pc.Stars, draw_count = pc.DrawPile.Cards.Count,
                hand = pc.Hand.Cards.Select((card, i) => owner.NoslInstance(card, i)).ToArray(),
                discard = pc.DiscardPile.Cards.Select((card, i) => owner.NoslInstance(card, i)).ToArray(),
                exhaust = PublicPile(pc.ExhaustPile.Cards.Select(NoslRow)),
                gold = combat.GetPlayerGold(player), powers = PublicPowers(combat, player.Creature),
                potions = Enumerable.Range(0, player.PotionSlots.Count)
                    .Select(i => combat.GetPotionAtSlot(player, i)?.Id.Entry).ToArray(),
                enemies = combat.KnownEnemies.Select(enemy => new
                {
                    enemy.CombatId, id = enemy.Monster?.Id.Entry,
                    hp = sim.State.GetCreature(enemy).CurrentHp,
                    block = sim.State.GetCreature(enemy).Block, powers = PublicPowers(combat, enemy),
                }).ToArray(),
            };
        }

        private Vertex Add(Vertex? parent, Move? move, Outcome? endpoint, string? key)
        {
            var tick = Stopwatch.GetTimestamp();
            Vertex? vertex = null;
            if (_mode != "tree" && key != null && _cache.TryGetValue(key, out vertex))
            {
                _hits++;
                if (vertex.Expanding) _cycles++;
            }
            bool fresh = vertex == null;
            var edge = parent == null ? null : new Edge(parent.Id, vertex?.Id ?? _vertices.Count, move!);
            if (fresh)
            {
                vertex = new Vertex(_vertices.Count, edge, endpoint);
                _vertices.Add(vertex);
                if (_mode != "tree" && key != null) _cache.Add(key, vertex);
            }
            if (edge != null)
            {
                _edges.Add(edge);
                parent!.Outgoing.Add(edge);
            }
            _lookupTicks += Stopwatch.GetTimestamp() - tick;
            return vertex!;
        }

        private bool Limit(int depth)
        {
            _maxDepth = Math.Max(_maxDepth, depth);
            if (_stop != null) return true;
            if (_transitions >= _cap) _stop = "transition_cap";
            else if (depth > _depth) _stop = "depth_cap";
            else if (_clock.ElapsedMilliseconds >= _wall) _stop = "wall_cap";
            else if (_transitions % 32 == 0)
            {
                _peakManaged = Math.Max(_peakManaged, GC.GetTotalMemory(false));
                if (_peakManaged >= _memory) _stop = "managed_memory_cap";
            }
            return _stop != null;
        }

        private void Spend(Action action, bool restoring)
        {
            if (Limit(0)) throw new BudgetException();
            using var probe = new SearchProbe(!_oracle).Enter();
            long begin = Stopwatch.GetTimestamp();
            _transitions++;
            try
            {
                action();
            }
            catch (Exception) when (probe.Boundary != null)
            {
                throw new RandomException(probe.Boundary, probe.Draw);
            }
            finally
            {
                var elapsed = Stopwatch.GetTimestamp() - begin;
                _transferTicks += elapsed;
                _forks += probe.Forks;
                _forkTicks += probe.ForkTicks;
                if (restoring)
                {
                    _restoreCalls++;
                    _restoreTicks += elapsed;
                }
            }
            if (probe.Boundary != null) throw new RandomException(probe.Boundary, probe.Draw);
        }

        private static string Append(string lineage, Move move, bool normalize) =>
            lineage + Encode(normalize && move.Kind == "play_card" ? move with { Index = null } : move);

        private string MeasureState(SimulationSnapshot state)
        {
            long tick = Stopwatch.GetTimestamp();
            try { return StateText(state); }
            finally { _keyTicks += Stopwatch.GetTimestamp() - tick; }
        }

        private void End(Vertex parent, Move move, SimulationSnapshot state, string kind, string? reason = null,
            object? conditions = null)
        {
            var stamp = MeasureState(state);
            var endpoint = new Outcome(kind, reason, HashText(Encode(new { stamp, move, conditions, kind, reason })),
                new { state = PublicState(state), conditions });
            // Edges keep each boundary occurrence. Distinct outcomes are counted by semantic stamp below.
            Add(parent, move, endpoint, null);
        }

        private (Move Move, PlanAction Plan)[] Menu(SimulationSnapshot state)
        {
            var tick = Stopwatch.GetTimestamp();
            try
            {
                owner.ObserveNosl(owner._root, state, previewMoves: false);
                var actions = owner._episodeMenu!.Select((option, i) =>
                {
                    var plan = option.Action;
                    return (new Move(plan.Kind == PlanActionKind.EndTurn ? "end_turn" : "play_card",
                        i, plan.Kind == PlanActionKind.PlayCard ? plan.CardId : null, plan.TargetCombatId), plan);
                }).ToList();
                if (!_potionsEnabled) return actions.ToArray();
                var sim = state.Simulator;
                var combat = (SimulatedCombatState)sim.State.CombatState;
                for (int i = 0; i < owner._player.PotionSlots.Count; i++)
                {
                    if (!combat.IsPotionAvailable(owner._player, i) ||
                        combat.GetPotionAtSlot(owner._player, i) is not { } potion) continue;
                    if (potion.Id.Entry is not ("FLEX_POTION" or "DEXTERITY_POTION" or "BLESSING_OF_THE_FORGE")
                        || potion.TargetType != TargetType.AnyPlayer || !potion.IsValidTarget(owner._player.Creature))
                        throw new NotSupportedException($"Potion menu is unqualified for {potion.Id.Entry}");
                    actions.Add((new Move("use_potion", i, potion.Id.Entry),
                        new PlanAction(PlanActionKind.UsePotion, state.Turn, PotionSlot: i, PotionId: potion.Id.Entry)));
                }
                return actions.ToArray();
            }
            finally { _menuTicks += Stopwatch.GetTimestamp() - tick; }
        }

        private void Explore(Vertex vertex, SimulationSnapshot state, string lineage, int depth)
        {
            (Move Move, PlanAction Plan)[] menu;
            try { menu = Menu(state); }
            catch (NotSupportedException error)
            {
                End(vertex, new Move("menu"), state, "unsupported", error.Message);
                return;
            }
            _maxMoves = Math.Max(_maxMoves, menu.Length);
            vertex.Expanding = true;
            try
            {
                foreach (var (move, plan) in menu)
                {
                    if (Limit(depth))
                    {
                        End(vertex, move, state, "budget", _stop);
                        continue;
                    }
                    var nextLineage = Append(lineage, move, _identityRule) +
                        (_identityRule && move.Kind == "play_card" ? Encode(plan.CardStateKey) : "");
                    if (move.Kind == "end_turn")
                    {
                        var endStamp = MeasureState(state);
                        var a = Add(vertex, move, new Outcome("end_play_a", null, HashText(endStamp),
                            new { state = PublicState(state) }), null);
                        Branch(a, new Move("settle_turn"), state, plan, [], nextLineage, depth);
                    }
                    else Branch(vertex, move, state, plan, [], nextLineage, depth);
                }
            }
            finally { vertex.Expanding = false; }
        }

        private void Branch(Vertex from, Move edge, SimulationSnapshot anchor, PlanAction plan,
            IReadOnlyList<int[]> choices, string lineage, int depth, SimulationSnapshot? before = null)
        {
            var solver = owner._pre0bSolver!;
            var previous = _verify ? MeasureState(anchor) : null;
            using var session = solver.OpenInteractiveCombat(anchor);
            try
            {
                if (Limit(depth)) throw new BudgetException();
                Spend(() => session.Play(plan), choices.Count > 0);
                for (int i = 0; i < choices.Count; i++)
                {
                    int[] choice = choices[i];
                    Spend(() => session.Select(choice), i < choices.Count - 1);
                }
                var next = session.Current;
                if (next.HasRisk)
                {
                    End(from, edge, anchor, "unsupported", "solver_risk", next.PredictionGaps.Select(g => g.Key).ToArray());
                    return;
                }
                if (session.Waiting)
                {
                    var spec = session.Choice;
                    if (!_oracle && (spec.SourcePile == PileType.Draw || spec.RandomizedReveal))
                    {
                        End(from, edge, before ?? anchor, "random", "unqualified_choice_reveal");
                        return;
                    }
                    var pending = Add(from, edge, null, null);
                    _choiceNodes++;
                    foreach (var selection in Selections(spec.Options.Count, spec.MinCount, spec.MaxCount, []))
                    {
                        var select = new Move("select", Selection: selection);
                        Branch(pending, select, anchor, plan, [.. choices, selection],
                            Append(lineage, select, false), depth + 1, next);
                        if (_stop != null) break;
                    }
                    return;
                }
                if (next.BoundaryReason != SearchBoundaryReason.None)
                    End(from, edge, anchor, "unsupported", next.BoundaryReason.ToString());
                else if (next.TerminalStamp != null)
                    End(from, edge, next, next.PlayerDead ? "death" : next.AllEnemiesDead ? "victory" : "unsupported");
                else if (next.Turn > seed.Turn)
                    End(from, edge, next, "next_turn_b");
                else
                {
                    string key = MeasureState(next) + lineage;
                    var child = Add(from, edge, null, key);
                    if (ReferenceEquals(child.Incoming, _edges[^1]))
                        Explore(child, next, lineage, depth + 1);
                }
            }
            catch (RandomException random)
            {
                End(from, edge, before ?? anchor, "random", random.Message, random.Conditions);
            }
            catch (BudgetException)
            {
                End(from, edge, before ?? anchor, "budget", _stop);
            }
            catch (Exception error) when (error is not OutOfMemoryException)
            {
                End(from, edge, before ?? anchor,
                    error is NotSupportedException or PredictionUnsupportedException ? "unsupported" : "error",
                    error.GetType().Name + ": " + error.Message);
            }
            finally
            {
                if (previous != null && previous != MeasureState(anchor))
                    throw new InvalidOperationException("Branch modified its parent state");
            }
        }

        private static IEnumerable<int[]> Selections(int count, int min, int max, int[] prefix)
        {
            if (prefix.Length >= min) yield return prefix;
            if (prefix.Length >= max) yield break;
            for (int i = 0; i < count; i++)
                if (!prefix.Contains(i))
                    foreach (var option in Selections(count, min, max, [.. prefix, i]))
                        yield return option;
        }

        private void Propagate()
        {
            // Reachability is computed after expansion so late incoming edges and cycles are included.
            var queue = new Queue<(int Node, int First)>();
            for (int i = 0; i < _vertices[0].Outgoing.Count; i++)
                queue.Enqueue((_vertices[0].Outgoing[i].To, i));
            while (queue.TryDequeue(out var item))
            {
                var vertex = _vertices[item.Node];
                if (!vertex.FirstActions.Add(item.First)) continue;
                foreach (var edge in vertex.Outgoing) queue.Enqueue((edge.To, item.First));
            }
        }

        private Move[] Witness(Vertex vertex)
        {
            var result = new List<Move>();
            for (var incoming = vertex.Incoming; incoming != null; incoming = _vertices[incoming.From].Incoming)
                result.Add(incoming.Action);
            result.Reverse();
            return result.ToArray();
        }

        internal Dictionary<string, object?> Run(bool waiting)
        {
            if (_mode is not ("tree" or "k0" or "k1") || _cap <= 0 || _wall <= 0 || _depth is < 1 or > 256 || _memory <= 0)
                throw new ArgumentException("Invalid SV1 settings");
            _identityRule = _mode == "k1" && !waiting && CanNormalizeIdentities();
            var root = Add(null, null, null, waiting ? null : MeasureState(seed));
            if (waiting || seed.BoundaryReason != SearchBoundaryReason.None || seed.TerminalStamp != null)
                End(root, new Move("root"), seed, "unsupported", "root_is_not_stable_player_decision");
            else Explore(root, seed, "", 0);
            Propagate();
            var endpoints = _vertices.Where(v => v.Outcome != null).ToArray();
            var groups = endpoints.GroupBy(v => (v.Outcome!.Kind, v.Outcome.State)).ToArray();
            var boundaryCounts = endpoints.GroupBy(v => v.Outcome!.Kind)
                .ToDictionary(group => group.Key, group => group.Count());
            var serialization = Stopwatch.GetTimestamp();
            var payload = JsonSerializer.SerializeToElement(new
            {
                root = PublicState(seed), first_actions = root.Outgoing.Select(edge => edge.Action),
                edges = _edges, endpoints = groups.Select(group => new
                {
                    node = group.First().Id, nodes = group.Select(v => v.Id).ToArray(), group.First().Outcome,
                    first_actions = group.SelectMany(v => v.FirstActions).Distinct().Order(),
                    witness = Witness(group.First()),
                }),
            }, Wire);
            var counts = new
            {
                state_nodes = _vertices.Count - endpoints.Length, vertices = _vertices.Count,
                transitions = _transitions, forks = _forks, restore_calls = _restoreCalls, cache_hits = _hits,
                cycles = _cycles, edges = _edges.Count, distinct_endpoints = groups.Length,
                choices = _choiceNodes, max_moves = _maxMoves, max_depth = _maxDepth,
                first_actions = root.Outgoing.Count, endpoints = boundaryCounts,
                random_types = endpoints.Where(v => v.Outcome!.Kind == "random")
                    .GroupBy(v => v.Outcome!.Reason!).ToDictionary(group => group.Key, group => group.Count()),
            };
            return new()
            {
                ["type"] = "sv1_graph", ["mode"] = _mode, ["oracle"] = _oracle,
                ["identity_rule"] = _identityRule, ["stop"] = _stop, ["counts"] = counts,
                ["graph"] = payload, ["peak_managed_sample_bytes"] = _peakManaged,
                ["timing"] = new
                {
                    search_ms = _clock.Elapsed.TotalMilliseconds,
                    menu_ms = Ms(_menuTicks), transition_ms = Ms(_transferTicks), fork_ms = Ms(_forkTicks),
                    restore_ms = Ms(_restoreTicks), key_ms = Ms(_keyTicks), cache_ms = Ms(_lookupTicks),
                    result_ms = Ms(Stopwatch.GetTimestamp() - serialization),
                },
            };
        }

        private sealed class BudgetException : Exception;
        private sealed class RandomException(string reason, object? conditions) : Exception(reason)
        {
            internal object? Conditions { get; } = conditions;
        }
    }
}
