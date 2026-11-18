using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CombatSolver;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Runs;
using Sts2Headless;

namespace OfflineSearchHarness;

internal static partial class RealCombat
{
    private static CombatState? _combat;
    private static CombatReplayOutcome? _ledger;
    private static CombatReplayOutcomeSnapshot? _terminal;
    private static CombatChoices? _choices;
    private static bool _patched;

    internal static Dictionary<string, object?> Run(RunSimulator sim, JsonElement request)
    {
        switch (request.GetProperty("cmd").GetString())
        {
            case "f1_begin":
                var live = CombatManager.Instance.DebugOnlyGetState() ?? throw new InvalidOperationException("No combat");
                var player = live.Players.Single();
                if (!CombatManager.Instance.IsInProgress || player.PlayerCombatState?.Phase != PlayerTurnPhase.Play)
                    throw new InvalidOperationException("Expected player play phase");
                _ledger?.Dispose();
                _combat = live;
                _terminal = null;
                _ledger = new CombatReplayOutcome(live);
                _choices = new CombatChoices(player, true, live, false);
                if (!_patched)
                {
                    var end = typeof(CombatManager).GetMethods(BindingFlags.NonPublic | BindingFlags.Instance)
                        .Single(m => m.Name == "EndCombatInternal" &&
                            m.GetParameters() is [{ ParameterType.Name: "CombatTurnState" }]);
                    new Harmony("m1-f1.terminal").Patch(end, prefix:
                        new HarmonyMethod(AccessTools.Method(typeof(RealCombat), nameof(CaptureTerminal))));
                    _patched = true;
                }
                return new()
                {
                    ["type"] = "f1_root", ["encounter"] = live.Encounter?.Id.Entry,
                    ["live"] = Hash(ContinuationStamp.CaptureLive(live).StateText),
                    ["resources"] = Resources(live),
                };
            case "f1_step":
                return TacticalStep(sim, request);
            case "f1_final":
                var combat = _combat ?? throw new InvalidOperationException("No bound combat");
                return new()
                {
                    ["type"] = "f1_final", ["terminal_callback"] = _terminal != null,
                    ["outcome"] = _terminal ?? _ledger!.Capture(combat, ended: false),
                    ["round"] = combat.RoundNumber,
                    ["resources"] = Resources(combat),
                    ["choice_requests"] = _choices!.Log, ["choice_checks"] = _choices.StateChecks,
                    ["choice_observation_ms"] = _choices.ObservationMs, ["choice_decision_ms"] = _choices.DecisionMs,
                };
            default:
                throw new InvalidOperationException("Unknown F1 request");
        }
    }

    private static Dictionary<string, object?> TacticalStep(RunSimulator sim, JsonElement request)
    {
        var combat = _combat ?? throw new InvalidOperationException("No bound combat");
        var player = combat.Players.Single();
        var pcs = player.PlayerCombatState!;
        if (!CombatManager.Instance.IsInProgress || pcs.Phase != PlayerTurnPhase.Play)
            throw new InvalidOperationException("Expected player play phase");
        var start = Stopwatch.GetTimestamp();
        var observation = Observe(combat);
        var observeMs = Stopwatch.GetElapsedTime(start).TotalMilliseconds;
        start = Stopwatch.GetTimestamp();
        var selected = Decide(observation, tactical: true);
        var decisionMs = Stopwatch.GetElapsedTime(start).TotalMilliseconds;
        var args = new Dictionary<string, object?>();
        string action = "end_turn";
        if (request.TryGetProperty("force", out var force))
        {
            action = force.GetProperty("action").GetString()!;
            foreach (var arg in force.GetProperty("args").EnumerateObject())
                args.Add(arg.Name, arg.Value.GetInt32());
            selected = action switch
            {
                "end_turn" when args.Count == 0 => null,
                "play_card" => observation.Moves.First(move => move.HandIndex == (int)args["card_index"]!
                    && TargetIndex(combat, move) == (args.TryGetValue("target_index", out var index) ? (int?)index : null)),
                _ => throw new InvalidOperationException("Unsupported forced action"),
            };
        }
        else if (selected != null)
        {
            action = "play_card";
            args["card_index"] = selected.HandIndex;
            if (TargetIndex(combat, selected) is int index)
                args["target_index"] = index;
        }

        var choices = _choices!;
        choices.Begin(request.GetProperty("step").GetInt32(), selected?.Id);
        start = Stopwatch.GetTimestamp();
        var decision = sim.ExecuteF1Action(player, choices, action, args);
        var executeMs = Stopwatch.GetElapsedTime(start).TotalMilliseconds;
        choices.Complete(!Equals(decision["type"], "error"),
            _terminal == null && CombatManager.Instance.IsInProgress && player.Creature.CurrentHp > 0);
        return new()
        {
            ["type"] = "f1_step", ["decision"] = decision, ["action"] = new { action, args },
            ["selected"] = selected, ["observation"] = observation,
            ["observe_ms"] = observeMs, ["decision_ms"] = decisionMs, ["execute_ms"] = executeMs,
            ["choice_failure"] = choices.Failure,
        };
    }

    private static int? TargetIndex(CombatState combat, Move move) => move.Target is uint id
        ? combat.Enemies.Where(enemy => enemy.IsAlive).ToList().FindIndex(enemy => enemy.CombatId == id)
        : null;

    private static object Resources(CombatState combat)
    {
        var player = combat.Players.Single();
        return new
        {
            hp = player.Creature.CurrentHp, max_hp = player.Creature.MaxHp, gold = player.Gold,
            deck = player.Deck.Cards.Select(CardChoiceSupport.ChoiceCardKey).ToArray(),
            potions = player.PotionSlots.Select(potion => potion?.Id.Entry).ToArray(),
            relics = player.Relics.Select(relic => relic.Id.Entry).ToArray(),
        };
    }

    private static void CaptureTerminal()
    {
        if (_combat != null)
            _terminal ??= _ledger!.Capture(_combat, ended: true);
    }

    private static string Hash(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
}
