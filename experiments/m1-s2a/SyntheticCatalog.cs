using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Runs;

namespace Sts2Headless;

public partial class RunSimulator
{
    internal Dictionary<string, object?> SyntheticCatalog()
    {
        EnsureModelDbInitialized();
        var characters = new[] { "Ironclad", "Silent" }.Select(name =>
        {
            var player = CreatePlayer(name)!;
            return new
            {
                name,
                max_hp = player.Creature.MaxHp,
                slots = player.PotionSlots.Count,
                relics = player.Relics.Select(r => r.Id.Entry).ToArray(),
                starter = player.Deck.Cards.Select(c => c.Id.Entry).ToArray(),
                cards = player.Character.CardPool.AllCards.Concat(player.Character.StartingDeck)
                    .DistinctBy(c => c.Id).OrderBy(c => c.Id.Entry, StringComparer.Ordinal)
                    .Select(c => new { id = c.Id.Entry, type = c.Type.ToString(),
                        rarity = c.Rarity.ToString(), upgradable = c.IsUpgradable }).ToArray(),
            };
        }).ToArray();
        var acts = ModelDb.ActsByIndex.Take(2).SelectMany((variants, index) => variants.Select(act => new
        {
            act = index + 1,
            variant = act.Id.Entry,
            encounters = act.AllEncounters.Select(e => new { id = e.Id.Entry, room = e.RoomType.ToString() })
                .DistinctBy(e => e.id).OrderBy(e => e.id, StringComparer.Ordinal).ToArray(),
        })).ToArray();
        return new()
        {
            ["type"] = "synthetic_catalog",
            ["characters"] = characters,
            ["acts"] = acts,
            ["potions"] = new[] { "FLEX_POTION", "DEXTERITY_POTION" }
                .Select(id => ModelDb.GetById<PotionModel>(new ModelId("POTION", id)).Id.Entry).ToArray(),
        };
    }
}
