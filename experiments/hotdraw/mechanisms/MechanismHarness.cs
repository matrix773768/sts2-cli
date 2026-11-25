using System.Diagnostics;
using System.Text.Json;
using CombatSolver;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;

namespace OfflineSearchHarness;

internal static partial class HotDrawHarness
{
    private static object RunMechanisms(UnattendedTestRequest request, HotRootBundle bundle)
    {
        var ids = BindFixtureInstances(request, bundle);
        var input = bundle.RootState;
        var draw = Enumerable.Range(input.HandCount + 1,
            request.Cards.Where(card => card.Pile == "Draw").Sum(card => card.Count)).Select(id => (ushort)id);
        var belief = DrawBelief.Create([], draw, []);
        var session = new Session(bundle.Rules);
        var start = session.Open(input, bundle.RootCold, belief, ids, true);
        ExportMechanisms(session, start, bundle.Rules);
        var clock = Stopwatch.StartNew();
        string exported = "";
        const int iterations = 25;
        for (int i = 0; i < iterations; i++)
            exported = ExportMechanisms(session, start, bundle.Rules);
        double meanMilliseconds = clock.Elapsed.TotalMilliseconds / iterations;

        for (int i = 0; i < input.DrawCount / 2; i++)
        {
            int left = input.DrawStart + i;
            int right = input.DrawStart + input.DrawCount - 1 - i;
            (input.Cards[left], input.Cards[right]) = (input.Cards[right], input.Cards[left]);
        }
        for (int i = 0; i < HotLimits.MaxRngStreams; i++)
            input.Rng[i] = HotRng.CreateFromSeed((ulong)(2041 + i));
        var alternate = session.Open(input, bundle.RootCold, belief, ids, true);
        if (exported != ExportMechanisms(session, alternate, bundle.Rules))
            throw new InvalidOperationException("Public export depends on hidden world.");
        using var document = JsonDocument.Parse(exported);
        return new { input = document.RootElement.Clone(), meanMilliseconds, iterations,
            fairness = new { hiddenDrawCount = input.DrawCount, replacedRngStreams = HotLimits.MaxRngStreams } };
    }

    private static string ExportMechanisms(Session session, Snapshot snapshot, HotRules rules)
    {
        var state = snapshot.State;
        using var projection = JsonDocument.Parse(session.PublicJson(snapshot));
        var cards = Enumerable.Range(0, state.TotalCardCount)
            .Select(i => (Card: state.Cards[i], InHand: i < state.HandCount)).ToArray();
        var cost = cards.OrderBy(item => item.Card.CardUid).Select(item =>
        {
            var card = item.Card;
            return new
            {
                instance = card.CardUid,
                effectiveEnergy = HotCombatEngine.GetEffectiveEnergyCost(in state, in card, snapshot.Cold, rules,
                    isInPlayablePile: item.InHand)
            };
        });
        var cardRules = cards.Select(item => item.Card.CardDefId).Distinct().OrderBy(id => rules.Cards[id].Entry, StringComparer.Ordinal)
            .Select(id =>
            {
                var def = rules.Cards[id];
                var ops = rules.GetCardOps(id).ToArray();
                return new
                {
                    def.Entry, def.Type, def.Target, def.BaseCost, def.UpgradedCost, def.BaseStarCost,
                    def.BaseKeywords, def.BaseDamage, def.UpgradedDamage, def.BaseBlock, def.UpgradedBlock,
                    def.BaseHits, def.UpgradedHits, def.BaseMagic, def.UpgradedMagic,
                    def.HookMask, def.CardId, def.CustomCardId, def.CustomHandlerId, def.CalcVar, def.CanGenerateUnknown,
                    def.OrderedVarNames, def.BaseVarValues, def.UpgradedVarValues,
                    operations = ops.Select(op => new { op.Op, Flags = (HotCardOpFlags)op.Flags, op.Arg0 }),
                    knownCustomSemantics = DescribeCustom(def.Entry),
                    coverage = def.CustomHandlerId != 0 || ops.Any(op => op.Op == HotCardOpKind.Custom)
                        ? "specialized_execution_unexpanded" : "catalog_operations_and_hook_references"
                };
            });
        var powerRules = Enumerable.Range(0, state.PowerCount).Select(i => state.Powers[i].PowerDefId)
            .Distinct().OrderBy(id => rules.Powers[id].Entry, StringComparer.Ordinal).Select(id =>
            {
                var def = rules.Powers[id];
                return new { def.Entry, def.Type, def.StackType, def.InstanceType, def.HookMask,
                    def.SpecialKind, def.OrderedVarNames, def.DefaultVarValues,
                    coverage = "hook_reference_runtime_payload_unqualified" };
            });
        var relicRules = rules.ActiveRelicDefIds.Select(id =>
        {
            var def = rules.Relics[id];
            return new { def.Entry, def.HookMask, def.SpecialKind, def.PrimaryValue, def.SecondaryValue,
                def.IsTracked, coverage = "hook_reference_runtime_payload_unqualified" };
        });
        var enemies = Enumerable.Range(0, state.EnemyCount).Select(slot =>
        {
            var enemy = state.Enemies[slot];
            var def = rules.Monsters[enemy.MonsterDefId];
            var machine = rules.GetMonsterMachine(enemy.MonsterDefId);
            return new { slot, def.Entry, def.StateKind, rules = machine == null ? null : ExportGraph(machine, rules) };
        });
        return JsonSerializer.Serialize(new
        {
            schema = 1,
            state = projection.RootElement,
            cardCosts = cost, cardRules, powerRules, relicRules, enemyRules = enemies,
            limitations = new[] { "fixture_public_instance_provenance_required", "private_ai_state_excluded",
                "unqualified_runtime_hook_state_excluded", "catalog_is_not_a_future_execution_certificate" }
        }, Json);
    }

    // Partial descriptions of the existing dispatch bodies in HotCombatEngine.Cards.Core.cs.
    private static string[] DescribeCustom(string entry) => entry switch
    {
        "FLASH_OF_STEEL" => ["attack_selected_enemy_once", "draw_one"],
        "BURNING_PACT" => ["if_hand_nonempty_choose_and_exhaust_hand_card", "draw_magic"],
        "HEADBUTT" => ["attack_selected_enemy_once", "if_ongoing_and_discard_nonempty_choose_discard_to_draw_top"],
        "OFFERING" => ["unblockable_self_hp_loss_HpLoss", "if_alive_gain_Energy", "if_alive_draw_Cards"],
        _ => []
    };

    private static object ExportGraph(HotMonsterMachine machine, HotRules rules)
    {
        string? Name(int index) => index < 0 || index >= machine.Nodes.Length ? null : machine.Nodes[index].MoveId;
        return new
        {
            initial = Name(machine.InitialNode), coverage = "catalog_graph_specialized_execution_unexpanded",
            nodes = machine.Nodes.Select(node => new
            {
                node.MoveId, node.NodeKind, node.BaseDamage, node.Repeats, node.RemovesOwnerOnMove,
                attacks = node.Attacks.Select(attack => new { attack.BaseDamage, attack.Repeats, attack.Flags }),
                effects = node.MoveEffects.Select(effect => new
                {
                    effect.Op, effect.Amount, effect.Flags, effect.TargetDefId,
                    power = effect.Op is HotCardOpKind.ApplyPowerSelf or HotCardOpKind.ApplyPowerTarget
                        or HotCardOpKind.ApplyPowerAllEnemies ? rules.Powers[effect.TargetDefId].Entry : null
                }),
                next = node.IsMove ? Name(node.NextNode) : null,
                targets = node.BranchTargets.Select(target => Name(target)),
                // Random branch weights are captured via live callbacks. Their
                // public reconstruction has not been qualified.
                weightsAvailable = false,
                repeatTypes = node.BranchRepeatTypes.Select(value => (int)value),
                maxTimes = node.BranchMaxTimes.Select(value => (int)value),
                cooldowns = node.BranchCooldowns.Select(value => (int)value),
                node.Cooldown, node.MustPerformOnceBeforeRepeat, node.CannotRepeat,
                node.ConditionalKind,
                condition = DescribeCondition(node.ConditionalKind),
                successor = node.IsMove ? "catalog_edge" : "unqualified"
            })
        };
    }

    // Dependencies and named edges read from HotMonsters.ResolveConditionalBranch.
    // The resolver's root-dependent fallback and private registers stay excluded.
    private static object? DescribeCondition(HotMonsterConditionalKind condition) => condition switch
    {
        HotMonsterConditionalKind.FrogKnightHalfHealth =>
            new { predicate = "already_charged_or_hp_at_least_floor_half", whenTrue = "TONGUE_LASH",
                whenFalse = "BEETLE_CHARGE", dependency = "current_max_hp_and_unqualified_charge_history" },
        HotMonsterConditionalKind.TestSubjectRevive =>
            new { predicate = "revive_phase_register_lt_2", whenTrue = "MULTI_CLAW_MOVE",
                whenFalse = "PHASE3_LACERATE_MOVE", dependency = "unqualified_revive_phase" },
        HotMonsterConditionalKind.LagavulinSleep =>
            new { predicate = "asleep_amount_positive", whenTrue = "SLEEP_MOVE",
                whenFalse = "SLASH_MOVE", dependency = "owner_asleep_power" },
        HotMonsterConditionalKind.SlumberingBeetleSnore =>
            new { predicate = "slumber_amount_positive", whenTrue = "SNORE_MOVE",
                whenFalse = "ROLL_OUT_MOVE", dependency = "owner_slumber_power" },
        _ => null
    };
}
