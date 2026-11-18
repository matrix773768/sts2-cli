using System.Diagnostics;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text.Json;
using CombatSolver;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.TestSupport;

namespace OfflineSearchHarness;

internal static class FastCombat
{
    private sealed record Enemy(uint? Id, int Hp, int Block, int Incoming);
    private sealed record Move(int HandIndex, string Id, uint? Target, int Damage, int Block, int Draw, int Energy, bool Power);
    private sealed record Observation(int Block, Enemy[] Enemies, List<Move> Moves);
    private static Func<CombatReplayOutcomeSnapshot>? _finish;
    private static CombatReplayOutcomeSnapshot? _terminal;

    private sealed class UnsupportedChoice : ICardSelector
    {
        public bool Requested { get; private set; }
        public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options, int minSelect, int maxSelect)
        {
            Requested = true;
            return Task.FromException<IEnumerable<CardModel>>(new NotSupportedException("combat_card_choice"));
        }

        public CardRewardSelection GetSelectedCardReward(IReadOnlyList<CardCreationResult> options,
            IReadOnlyList<CardRewardAlternative> alternatives)
        {
            Requested = true;
            throw new NotSupportedException("combat_card_reward_choice");
        }
    }

    private static Observation Observe(CombatState combat)
    {
        var player = combat.Players.Single();
        var pcs = player.PlayerCombatState!;
        var targets = combat.Enemies.Where(e => e.CurrentHp > 0 && e.IsHittable).ToArray();
        Enemy[] enemies = targets.Select(e => new Enemy(e.CombatId, e.CurrentHp, e.Block,
            e.Monster?.NextMove?.Intents.OfType<AttackIntent>()
                .Sum(intent => intent.GetTotalDamage([player.Creature], e)) ?? 0)).ToArray();
        List<Move> moves = [];
        for (int i = 0; i < pcs.Hand.Cards.Count; i++)
        {
            var card = pcs.Hand.Cards[i];
            if (!card.CanPlay(out _, out _))
                continue;
            IEnumerable<Creature?> candidates = card.TargetType == TargetType.AnyEnemy ? targets : new Creature?[] { null };
            foreach (var target in candidates)
            {
                if (!card.CanPlayTargeting(target))
                    continue;
                int Value(string name) => (int)(card.DynamicVars.Values.FirstOrDefault(v => v.Name.Equals(name, StringComparison.OrdinalIgnoreCase))?.PreviewValue ?? 0);
                card.DynamicVars.ClearPreview();
                try
                {
                    card.UpdateDynamicVarPreview(target == null ? CardPreviewMode.Normal : CardPreviewMode.MultiCreatureTargeting,
                        target, card.DynamicVars);
                    int damage = Math.Max(Value("damage"), Value("calculateddamage")) * Math.Max(1, Value("repeat"));
                    moves.Add(new(i, card.Id.Entry, target?.CombatId, damage, Value("block"),
                        Value("cards"), card.EnergyCost?.GetResolved() ?? 0, card.Type == CardType.Power));
                }
                finally
                {
                    card.DynamicVars.ClearPreview();
                }
            }
        }
        return new(player.Creature.Block, enemies, moves);
    }

    private static Move? Decide(Observation state, bool tactical)
    {
        if (!tactical)
            return state.Moves.Count > 0 ? state.Moves[0] : null;
        int incoming = state.Enemies.Sum(e => e.Incoming);
        Move? best = null;
        int bestScore = 0;
        foreach (var move in state.Moves)
        {
            Enemy? target = move.Target == null ? null : state.Enemies.First(e => e.Id == move.Target);
            int dealt = target == null ? move.Damage : Math.Clamp(move.Damage - target.Block, 0, target.Hp);
            bool lethal = target != null && dealt >= target.Hp;
            int blocked = Math.Min(move.Block, Math.Max(0, incoming - state.Block));
            int score = 3 * dealt + 5 * blocked + (lethal ? 30 + 5 * target!.Incoming : 0)
                + 4 * move.Draw + (move.Power ? 5 : 0) - 2 * move.Energy + (move.Energy == 0 ? 1 : 0);
            if (score > bestScore)
            {
                best = move;
                bestScore = score;
            }
        }
        return best;
    }

    internal static void Run(CombatState combat, MainLoopContext loop, string output)
    {
        bool tactical = Environment.GetEnvironmentVariable("M1Q1_POLICY") == "tactical";
        bool warm = Environment.GetEnvironmentVariable("M1Q1_WARM") == "1";
        var root = CombatRootSnapshot.Capture(combat);
        var player = combat.Players.Single();
        var pcs = player.PlayerCombatState!;
        var manager = CombatManager.Instance;
        var executor = RunManager.Instance.ActionExecutor;
        InstallHooks();
        using var ledger = new CombatReplayOutcome(combat);
        _finish = () => ledger.Capture(combat, ended: true);
        var selector = new UnsupportedChoice();
        using var choices = NativeTestCardSelectors.Push(selector);
        var warmup = Stopwatch.StartNew();
        if (warm)
        {
            for (int i = 0; i < 128; i++)
                _ = Decide(Observe(combat), tactical);
            if (ContinuationStamp.CaptureLive(combat).StateText != root.LiveStamp.StateText)
                throw new InvalidOperationException("Warmup mutated the native root");
        }
        warmup.Stop();

        var battle = Stopwatch.StartNew();
        var steps = new List<object>();
        string status = "limit";
        for (int i = 0; i < 140 && battle.Elapsed.TotalSeconds < 20; i++)
        {
            if (_terminal != null || !manager.IsInProgress || player.Creature.CurrentHp <= 0)
                break;
            if (pcs.Phase != PlayerTurnPhase.Play)
            {
                status = "unsupported_phase";
                break;
            }
            int turn = pcs.TurnNumber;
            long start = Stopwatch.GetTimestamp();
            var visible = Observe(combat);
            double observeMs = Stopwatch.GetElapsedTime(start).TotalMilliseconds;
            start = Stopwatch.GetTimestamp();
            Move? selected = Decide(visible, tactical);
            double decisionMs = Stopwatch.GetElapsedTime(start).TotalMilliseconds;
            start = Stopwatch.GetTimestamp();
            int before = player.Creature.CurrentHp;
            try
            {
                if (selected == null)
                {
                    manager.OnEndedTurnLocally();
                    RunManager.Instance.ActionQueueSynchronizer.RequestEnqueue(new EndPlayerTurnAction(player, turn));
                }
                else
                {
                    var card = pcs.Hand.Cards[selected.HandIndex];
                    var target = selected.Target is uint id ? combat.Enemies.Single(e => e.CombatId == id) : null;
                    if (!card.CanPlayTargeting(target) || !card.TryManualPlay(target))
                        throw new InvalidOperationException($"Native rejected {selected.Id}");
                }
                loop.RunUntilCompleted(executor.FinishedExecutingActions(), TimeSpan.FromSeconds(3), "Q1 native action");
                while (selected == null && manager.IsInProgress && _terminal == null && !selector.Requested
                    && (pcs.TurnNumber <= turn || pcs.Phase != PlayerTurnPhase.Play))
                {
                    if (Stopwatch.GetElapsedTime(start).TotalSeconds > 3) throw new TimeoutException("Q1 turn");
                    loop.Pump(TimeSpan.FromMilliseconds(1));
                }
            }
            catch (Exception) when (selector.Requested) { }
            catch (TimeoutException) { status = "execution_timeout"; }
            double executeMs = Stopwatch.GetElapsedTime(start).TotalMilliseconds;
            steps.Add(new { turn, selected, observeMs, decisionMs, executeMs, before, after = player.Creature.CurrentHp,
                block = visible.Block, enemies = visible.Enemies });
            if (selector.Requested || status == "execution_timeout")
            {
                if (selector.Requested) status = "unsupported_choice";
                break;
            }
        }
        battle.Stop();
        var outcome = _terminal ?? ledger.Capture(combat, ended: false);
        if (status == "limit" && _terminal != null && !manager.IsInProgress && outcome.Survived && outcome.FinalEnemyHp == 0)
            status = "win";
        else if (status == "limit" && !outcome.Survived)
            status = "death";
        File.WriteAllText(Path.Combine(output, "fast.json"), JsonSerializer.Serialize(new
        {
            status, tactical, warm, warmMs = warmup.Elapsed.TotalMilliseconds, battleMs = battle.Elapsed.TotalMilliseconds,
            root = Hash(root.ContinuationStamp.StateText), live = Hash(root.LiveStamp.StateText),
            endTurn = pcs.TurnNumber, outcome, postCombatHp = player.Creature.CurrentHp,
            peakMiB = Process.GetCurrentProcess().PeakWorkingSet64 / 1048576.0, steps,
        }, UnattendedTestFiles.JsonOptions));
    }

    private static string Hash(string value) => Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(
        System.Text.Encoding.UTF8.GetBytes(JsonSerializer.Serialize(value)))).ToLowerInvariant();

    private static void InstallHooks()
    {
        var patch = new Harmony("m1-q1.native");
        var end = typeof(CombatManager).GetMethods(BindingFlags.NonPublic | BindingFlags.Instance)
            .Single(m => m.Name == "EndCombatInternal" && m.GetParameters() is [{ ParameterType.Name: "CombatTurnState" }]);
        var wrapper = AccessTools.Method(typeof(CardModel), "OnPlayWrapper");
        var moveNext = AccessTools.Method(wrapper.GetCustomAttribute<AsyncStateMachineAttribute>()!.StateMachineType, "MoveNext");
        patch.Patch(end, prefix: Hook(nameof(CaptureTerminal)));
        patch.Patch(moveNext, transpiler: Hook("Timer"));
        patch.Patch(AccessTools.Method(typeof(RunManager), "WriteReplay", [typeof(bool)]), prefix: Hook("Skip"));
        patch.Patch(AccessTools.Method(AccessTools.TypeByName("NHoverTipSet"), "Clear", []), prefix: Hook("Skip"));
    }

    private static HarmonyMethod Hook(string name) => new(AccessTools.Method(
        name == nameof(CaptureTerminal) ? typeof(FastCombat) : typeof(NativeWitness), name));
    private static void CaptureTerminal() => _terminal ??= _finish?.Invoke();
}
