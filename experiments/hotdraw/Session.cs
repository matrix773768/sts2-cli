using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using CombatSolver.HotKernel;

namespace CombatSolver.HotDraw;

internal sealed class Snapshot(in CombatHotState state, HotColdSidecar? cold, DrawBelief belief)
{
    internal readonly CombatHotState State = state;
    internal readonly HotColdSidecar? Cold = cold;
    internal readonly DrawBelief Belief = belief;
}

internal sealed record Transition(StepStatus Status, HotCombatOutcome Outcome, Snapshot? Child,
    StepEvent[] Events, string? Reason, string? Point, int LogicalShuffles, long BeliefTicks)
{
    public StepEvent Pending => Events[^1];
}

internal sealed class Session(HotRules rules)
{
    private static readonly HashSet<string> QualifiedCards = new(StringComparer.Ordinal)
    {
        "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "POMMEL_STRIKE", "SHRUG_IT_OFF", "BATTLE_TRANCE", "BASH",
        "FLASH_OF_STEEL", "FINESSE", "BURNING_PACT", "DARK_EMBRACE", "HEADBUTT", "PREPARED",
        "OFFERING", "BLOODLETTING", "AUTOMATION", "VOID", "HAVOC", "REGRET"
    };
    private static readonly HashSet<string> QualifiedPowers = new(StringComparer.Ordinal)
    {
        "STRENGTH_POWER", "DEXTERITY_POWER", "WEAK_POWER", "VULNERABLE_POWER", "FRAIL_POWER",
        "DARK_EMBRACE_POWER", "NO_DRAW_POWER", "AUTOMATION_POWER", "CONFUSED_POWER", "ITERATION_POWER"
    };
    private static readonly HashSet<string> QualifiedRelics = new(StringComparer.Ordinal)
    {
        "BURNING_BLOOD", "THE_ABACUS"
    };

    // Import requires trusted public provenance for the entire belief and a mapping produced
    // independently of hidden draw position. Oracle fixtures may keep their native IDs.
    public Snapshot Open(in CombatHotState input, HotColdSidecar? cold, DrawBelief belief,
        IReadOnlyDictionary<ushort, ushort> publicIds, bool exchangeable, bool keepWorldOrder = false)
    {
        if (!exchangeable)
            throw new Boundary(StepStatus.Unsupported, "non_exchangeable_constraints", "Import");
        CombatHotState state = input;
        if (state.CurrentSide != HotCombatSide.Player || state.PlayCount != 0)
            throw new Boundary(StepStatus.Unsupported, "unstable_root", "Import");
        if (publicIds.Values.Contains((ushort)0) || publicIds.Values.Distinct().Count() != publicIds.Count)
            throw new ArgumentException("Public instance mapping must be one-to-one and nonzero.");
        ushort Id(ushort privateId) => privateId == 0 ? (ushort)0 : publicIds[privateId];
        for (int i = 0; i < state.TotalCardCount; i++)
            state.Cards[i].CardUid = Id(state.Cards[i].CardUid);
        state.HistoryCourseUid = Id(state.HistoryCourseUid);
        state.HistoryCourseCard.CardUid = Id(state.HistoryCourseCard.CardUid);
        for (int i = 0; i < 3; i++)
            state.Fool.FirstPlayCardUid[i] = Id(state.Fool.FirstPlayCardUid[i]);
        for (int i = 0; i < state.PowerCount; i++)
            state.Powers[i].AuxCardUid = Id(state.Powers[i].AuxCardUid);
        if (cold != null)
        {
            cold = cold with
            {
                DetachedCards = cold.DetachedCards?.Select(card =>
                {
                    card.CardUid = Id(card.CardUid);
                    return card;
                }).ToArray(),
                DecimalVars = cold.DecimalVars?.Select(item => item with { CardUid = Id(item.CardUid) }).ToArray(),
                CostOverflow = cold.CostOverflow?.Select(item => item with { CardUid = Id(item.CardUid) }).ToArray(),
                RuptureEntries = cold.RuptureEntries?.Select(item => item with { CardUid = Id(item.CardUid) }).ToArray(),
                DampenEntries = cold.DampenEntries?.Select(item => item with { CardUid = Id(item.CardUid) }).ToArray(),
            };
        }
        state.NextCardUid = checked((ushort)(publicIds.Values.DefaultIfEmpty((ushort)0).Max() + 1));
        if (keepWorldOrder)
            state.NextCardUid = input.NextCardUid;
        belief.Validate(in state, keepWorldOrder: true);
        if (!keepWorldOrder)
        {
            var unknown = new Dictionary<ushort, HotCard>(belief.Unknown.Length);
            int start = state.DrawStart + belief.Top.Length;
            for (int i = 0; i < belief.Unknown.Length; i++)
            {
                HotCard card = state.Cards[start + i];
                unknown.Add(card.CardUid, card);
            }
            for (int i = 0; i < belief.Unknown.Length; i++)
                state.Cards[start + i] = unknown[belief.Unknown[i]];
            state.Rng = default;
        }
        return new Snapshot(in state, cold, belief);
    }

    public HotAction[] Actions(Snapshot snapshot, bool includeEndTurn)
    {
        Span<HotAction> actions = stackalloc HotAction[HotLimits.MaxCards * (HotLimits.MaxEnemies + 1) + 1];
        int count = HotCombatEngine.EnumerateLegalActions(in snapshot.State, snapshot.Cold, rules, actions);
        return actions[..count].ToArray()
            .Where(action => includeEndTurn || action.Kind != HotActionKind.EndTurn).ToArray();
    }

    public string ActionName(Snapshot snapshot, HotAction action) => action.Kind == HotActionKind.PlayCard
        ? $"{rules.Cards[snapshot.State.Cards[action.SlotOrHandIdx].CardDefId].Entry}#{snapshot.State.Cards[action.SlotOrHandIdx].CardUid}@{action.TargetEnemySlot}"
        : action.Kind.ToString();

    public Transition Advance(Snapshot parent, HotAction action, Prefix prefix,
        Resolution resolution = Resolution.Public)
    {
        if (Probe.Current != null)
            throw new InvalidOperationException("An independent top-level snapshot is required.");
        CombatHotState state = parent.State;
        HotColdSidecar? cold = parent.Cold;
        HotExecScratch scratch = new();
        bool fixedWorld = resolution != Resolution.Public;
        var probe = new Probe(rules, parent.Belief, prefix, action.Kind.ToString(), resolution);
        var status = StepStatus.Completed;
        string? reason = null;
        string? point = null;
        try
        {
            if (!Actions(parent, includeEndTurn: true).Contains(action))
                throw new InvalidOperationException("Action is absent from the legal menu.");
            probe = new Probe(rules, parent.Belief, prefix, ActionName(parent, action), resolution);
            Qualify(in state, action, probe);
            Probe.Current = probe;
            HotStepResult executed = HotCombatEngine.Step(ref state, ref cold, rules, scratch, action);
            if (!executed.Executed || executed.NeedsChoice)
                throw new InvalidOperationException("HotKernel returned an unhandled action boundary.");
            probe.RequireConsumed();
            probe.Belief.Validate(in state, keepWorldOrder: fixedWorld);
        }
        catch (Boundary boundary)
        {
            status = boundary.Status;
            reason = boundary.Message;
            point = boundary.Point;
        }
        catch (HotCapacityExceededException error)
        {
            status = StepStatus.Unsupported;
            reason = error.Message;
            point = "HotKernelCapacity";
        }
        catch (Exception error) when (error is InvalidOperationException or ArgumentException or KeyNotFoundException)
        {
            status = StepStatus.Error;
            reason = error.Message;
            point = error.TargetSite?.Name;
        }
        finally
        {
            Probe.Current = null;
            HotCombatEngine.ClearPendingChoiceUidFilters();
        }
        if (scratch.ActiveDrawDepth != 0)
            throw new InvalidOperationException("Draw stack did not unwind.");
        Snapshot? child = status == StepStatus.Completed ? new Snapshot(in state, cold, probe.Belief) : null;
        return new Transition(status, child?.State.TerminalOutcome ?? HotCombatOutcome.Ongoing, child,
            probe.Events.ToArray(), reason, point, probe.LogicalShuffleCalls, probe.BeliefTicks);
    }

    private void Qualify(in CombatHotState state, HotAction action, Probe probe)
    {
        if (rules.EncounterEntry != "FUZZY_WURM_CRAWLER_WEAK" || state.EnemyCount != 1
            || rules.Dominion != HotDominionId.None || state.OrbCapacity != 0 || state.ArrowCount != 0
            || rules.RootPets.Length != 0)
            probe.Reject("unqualified_encounter_or_rules", "Step");
        foreach (ushort defId in rules.ActiveRelicDefIds)
        {
            string entry = rules.Relics[defId].Entry;
            if (!QualifiedRelics.Contains(entry))
                probe.Reject("unqualified_relic", entry);
        }
        for (int i = 0; i < state.PowerCount; i++)
        {
            string entry = rules.Powers[state.Powers[i].PowerDefId].Entry;
            if (!QualifiedPowers.Contains(entry))
                probe.Reject("unqualified_power", entry);
        }
        for (int i = 0; i < state.TotalCardCount; i++)
        {
            ref readonly HotCard card = ref state.Cards[i];
            string entry = rules.Cards[card.CardDefId].Entry;
            if (!QualifiedCards.Contains(entry) || card.AfflId != 0)
                probe.Reject("unqualified_card_or_affliction", entry);
            if (card.EnchId != 0 && rules.Enchantments[card.EnchId].EnchantmentId
                is not (HotEnchantmentId.PerfectFit or HotEnchantmentId.Slither))
                probe.Reject("unqualified_enchantment", entry);
            if (action.Kind == HotActionKind.TurnSetup && state.PlayerTurnNumber == 1 &&
                (card.LocalKeywordsMask & HotCardKeywordMask.Innate) != 0)
                probe.Reject("initial_order_modifier", entry);
        }
        if (action.Kind == HotActionKind.PlayCard && rules.Cards[state.Cards[action.SlotOrHandIdx].CardDefId].Entry == "HAVOC")
            probe.Reject("autoplay_from_draw", "HAVOC");
    }

    public string PublicJson(Snapshot snapshot)
    {
        CombatHotState state = snapshot.State;
        var cardsById = new Dictionary<ushort, object>();
        for (int i = 0; i < state.TotalCardCount; i++)
        {
            HotCard card = state.Cards[i];
            var overflow = snapshot.Cold?.CostOverflow?.SingleOrDefault(item => item.CardUid == card.CardUid);
            cardsById.Add(card.CardUid, new
            {
                instance = card.CardUid, card = rules.Cards[card.CardDefId].Entry, upgrade = card.UpgradeLevel,
                card.BaseEnergyCost, card.BaseStarCost, card.TempStarCostPacked, card.Var0Delta, card.Var1Delta,
                card.BaseReplayCount, card.ExtraReplayThisTurn,
                keywords = card.LocalKeywordsMask, card.Flags, card.EnchAmt, card.EnchStatus, card.AfflAmt,
                enchantment = card.EnchId == 0 ? null : rules.Enchantments[card.EnchId].Entry,
                affliction = card.AfflId == 0 ? null : rules.Afflictions[card.AfflId].Entry,
                energyMods = Enumerable.Range(0, Math.Min((int)card.CostModCount, 4))
                    .Select(j => new { card.EnergyCostMods[j].Amount, card.EnergyCostMods[j].PackedFlags }).ToArray(),
                costOverflow = overflow?.EnergyMods.Select(mod => new { mod.Amount, mod.PackedFlags }).ToArray(),
                starOverflow = overflow?.TempStarCosts,
                decimalDelta = HotColdSidecar.GetDecimalVarDelta(snapshot.Cold, card.CardUid)
            });
        }
        object[] Zone(in CombatHotState current, HotPileKind zone)
        {
            int start = HotPiles.ZoneStart(in current, zone);
            var cards = new object[HotPiles.ZoneCount(in current, zone)];
            for (int i = 0; i < cards.Length; i++)
                cards[i] = cardsById[current.Cards[start + i].CardUid];
            return cards;
        }

        return JsonSerializer.Serialize(new
        {
            encounter = rules.EncounterEntry, turn = state.PlayerTurnNumber, state.PlayerPhase,
            hp = state.Player.CurrentHp, maxHp = state.Player.MaxHp, block = state.Player.Block,
            state.Energy, state.Stars, state.Gold, state.MaxHandSize, state.TerminalOutcome,
            hand = Zone(in state, HotPileKind.Hand), play = Zone(in state, HotPileKind.Play),
            discard = Zone(in state, HotPileKind.Discard), exhaust = Zone(in state, HotPileKind.Exhaust),
            knownTop = snapshot.Belief.Top.Select(id => cardsById[id]),
            unknown = snapshot.Belief.Unknown.Select(id => cardsById[id]),
            knownBottom = snapshot.Belief.Bottom.Select(id => cardsById[id]),
            snapshot.Belief.Generation,
            relics = rules.ActiveRelicDefIds.Select(id => rules.Relics[id].Entry),
            powers = Enumerable.Range(0, state.PowerCount).Select(i =>
                new { id = rules.Powers[state.Powers[i].PowerDefId].Entry, state.Powers[i].OwnerSlot, state.Powers[i].Amount }),
            enemies = Enumerable.Range(0, state.EnemyCount).Select(i =>
            {
                HotEnemy enemy = state.Enemies[i];
                var machine = rules.GetMonsterMachine(enemy.MonsterDefId);
                string? move = machine != null && enemy.CurrentMoveNode >= 0
                    ? machine.Nodes[enemy.CurrentMoveNode].MoveId : null;
                return new { slot = i, enemy.Vital.CurrentHp, enemy.Vital.MaxHp, enemy.Vital.Block, move };
            })
        });
    }

    // Display/audit key only. Search keeps all paths and does not use it for transpositions.
    public string PublicKey(Snapshot snapshot)
        => Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(PublicJson(snapshot))));
}
