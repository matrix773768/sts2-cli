using System.Text.Json;
using System.Text.Json.Serialization;
using CombatSolver;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;

namespace Sts2Headless;

internal sealed record SyntheticCard(string Id, int Upgrade);
internal sealed record SyntheticCombatSpec(int Schema, string Character, int Ascension, string Encounter,
    string Seed, SyntheticCard[] Deck, int Hp, int MaxHp, string[] Relics, string?[] Potions);

public partial class RunSimulator
{
    private static readonly JsonSerializerOptions SyntheticJson = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        RespectRequiredConstructorParameters = true,
    };

    internal Dictionary<string, object?> StartSyntheticCombat(JsonElement request)
    {
        if (_runState != null)
            return Error("Synthetic combat requires a fresh process");
        _loc.Lang = "en";
        EnsureModelDbInitialized();
        var spec = request.GetProperty("spec").Deserialize<SyntheticCombatSpec>(SyntheticJson)!;
        if (spec is null || spec.Schema != 1 || string.IsNullOrWhiteSpace(spec.Character)
            || string.IsNullOrWhiteSpace(spec.Encounter) || string.IsNullOrWhiteSpace(spec.Seed) || spec.Ascension is < 0 or > 10
            || spec.Hp < 1 || spec.MaxHp < spec.Hp || spec.MaxHp > 999
            || spec.Deck is not { Length: >= 1 and <= 40 }
            || spec.Relics is null || spec.Potions is null)
            return Error("Invalid synthetic combat spec");

        // Limit hook-bearing resource models to the supported spike surface.
        if (spec.Relics.Any(r => r is not "BURNING_BLOOD")
            || spec.Relics.Distinct().Count() != spec.Relics.Length
            || spec.Potions.Any(p => p is not (null or "FLEX_POTION")))
            return Error("Unsupported synthetic relic or potion");

        var player = CreatePlayer(spec.Character) ?? throw new ArgumentException("Unknown character");
        var encounter = ModelDb.GetById<EncounterModel>(new ModelId("ENCOUNTER", spec.Encounter)).ToMutable();
        var acts = ActModel.GetDefaultList().Select(a => a.ToMutable()).ToArray();
        if (encounter.RoomType != RoomType.Monster || !acts[0].AllEncounters.Any(e => e.Id == encounter.Id))
            return Error("Synthetic combat supports ordinary encounters from the default first act");
        var deck = spec.Deck.Select(c =>
        {
            if (c is null || c.Upgrade is < 0 or > 1)
                throw new ArgumentException("Expected upgrade level 0 or 1");
            return (model: ModelDb.GetById<CardModel>(new ModelId("CARD", c.Id)), c.Upgrade);
        }).ToArray();

        var manager = RunManager.Instance;
        _runState = RunState.CreateForNewRun([player], acts, [], GameMode.Standard,
            isCustom: false, ascensionLevel: spec.Ascension, seed: spec.Seed);
        manager.SetUpNewSingleplayer(_runState, shouldSave: false);
        manager.CombatReplayWriter.IsEnabled = false;
        LocalContext.NetId = player.NetId;
        _cardSelectorScope = manager.CardSelectorStack.UseSelector(player, _cardSelector);
        LocPatches._bundleSimRef = this;
        CombatManager.Instance.TurnStarted += _ => _turnStarted.Set();
        CombatManager.Instance.CombatEnded += _ => _combatEnded.Set();
        manager.FinalizeStartingRelics().GetAwaiter().GetResult();
        manager.Launch();

        foreach (var relic in player.Relics.Where(r => !spec.Relics.Contains(r.Id.Entry)).ToArray())
            RelicCmd.Remove(relic).GetAwaiter().GetResult();
        foreach (var id in spec.Relics.Where(id => !player.Relics.Any(r => r.Id.Entry == id)))
            RelicCmd.Obtain(ModelDb.GetById<RelicModel>(new ModelId("RELIC", id)).ToMutable(), player)
                .GetAwaiter().GetResult();

        foreach (var card in player.Deck.Cards.ToArray())
            _runState.RemoveCard(card);
        player.Deck.Clear(silent: true);
        foreach (var (model, upgrade) in deck)
        {
            var card = _runState.CreateCard(model, player);
            player.Deck.AddInternal(card, silent: true);
            if (upgrade == 1)
            {
                if (!card.IsUpgradable)
                    throw new ArgumentException($"Cannot upgrade {card.Id}");
                card.UpgradeInternal();
                card.FinalizeUpgradeInternal();
            }
        }

        if (spec.Potions.Length > player.PotionSlots.Count)
            return Error("Synthetic potions exceed native slot capacity");
        foreach (var potion in player.Potions.ToArray())
            PotionCmd.Discard(potion).GetAwaiter().GetResult();
        for (int slot = 0; slot < spec.Potions.Length; slot++)
        {
            if (spec.Potions[slot] is not string id)
                continue;
            var potion = ModelDb.GetById<PotionModel>(new ModelId("POTION", id)).ToMutable();
            PotionCmd.TryToProcure(potion, player, slot).GetAwaiter().GetResult();
            if (!ReferenceEquals(player.PotionSlots[slot], potion))
                return Error("Native potion procurement failed");
        }
        CreatureCmd.SetMaxHp(player.Creature, spec.MaxHp).GetAwaiter().GetResult();
        CreatureCmd.SetCurrentHp(player.Creature, spec.Hp).GetAwaiter().GetResult();

        manager.EnterRoomDebug(encounter.RoomType, MapPointType.Unassigned, encounter, showTransition: false)
            .GetAwaiter().GetResult();
        _syncCtx.Pump();
        WaitForActionExecutor();
        return DetectDecisionPoint();
    }

    // The game serializes RNG counters and state words as fields, not properties.
    private static readonly JsonSerializerOptions SyntheticRngJson = new() { IncludeFields = true };

    internal Dictionary<string, object?> SyntheticSnapshot()
    {
        var run = _runState ?? throw new InvalidOperationException("No synthetic combat");
        var player = run.Players.Single();
        var combat = CombatManager.Instance.DebugOnlyGetState()
            ?? throw new InvalidOperationException("No live combat");
        var pcs = player.PlayerCombatState!;
        return new()
        {
            ["type"] = "synthetic_snapshot",
            ["seed"] = run.Rng.StringSeed,
            ["character"] = player.Character.Id.Entry,
            ["ascension"] = run.AscensionLevel,
            ["should_save"] = RunManager.Instance.ShouldSave,
            ["replay_writer_enabled"] = RunManager.Instance.CombatReplayWriter.IsEnabled,
            ["visited_map_nodes"] = run.VisitedMapCoords.Count,
            ["run_rng"] = JsonSerializer.SerializeToElement(run.Rng.ToSerializable(), SyntheticRngJson),
            ["player_rng"] = JsonSerializer.SerializeToElement(player.PlayerRng.ToSerializable(), SyntheticRngJson),
            ["deck"] = player.Deck.Cards.Select(c => new SyntheticCard(c.Id.Entry, c.CurrentUpgradeLevel)).ToArray(),
            ["hand"] = pcs.Hand.Cards.Select(CardChoiceSupport.ChoiceCardKey).ToArray(),
            ["draw"] = pcs.DrawPile.Cards.Select(CardChoiceSupport.ChoiceCardKey).ToArray(),
            ["discard"] = pcs.DiscardPile.Cards.Select(CardChoiceSupport.ChoiceCardKey).ToArray(),
            ["exhaust"] = pcs.ExhaustPile.Cards.Select(CardChoiceSupport.ChoiceCardKey).ToArray(),
            ["continuation"] = ContinuationStamp.CaptureLive(combat).StateText,
        };
    }
}
