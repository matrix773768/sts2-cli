using MegaCrit.Sts2.Core.Models;

namespace Sts2Headless;

public partial class RunSimulator
{
    internal Dictionary<string, object?> Ls2Catalog()
    {
        EnsureModelDbInitialized();
        var characters = new List<object>();
        var unavailable = new List<string>();
        foreach (var character in ModelDb.AllCharacters.OrderBy(c => c.Id.Entry, StringComparer.Ordinal))
        {
            var name = character.GetType().Name;
            var player = CreatePlayer(name);
            if (player == null)
            {
                unavailable.Add(character.Id.Entry);
                continue;
            }
            characters.Add(new
            {
                name, id = character.Id.Entry, max_hp = player.Creature.MaxHp, slots = player.PotionSlots.Count,
                relics = player.Relics.Select(r => r.Id.Entry).ToArray(),
                starter = player.Deck.Cards.Select(c => c.Id.Entry).ToArray(),
                cards = character.CardPool.AllCards.Concat(character.StartingDeck)
                    .DistinctBy(c => c.Id).OrderBy(c => c.Id.Entry, StringComparer.Ordinal)
                    .Select(c => new
                    {
                        id = c.Id.Entry, type = c.Type.ToString(), rarity = c.Rarity.ToString(),
                        upgradable = c.IsUpgradable, target_type = c.TargetType.ToString(),
                        keywords = c.Keywords.Select(k => k.ToString()).Order(StringComparer.Ordinal).ToArray(),
                        variables = c.DynamicVars.Values.Select(v => v.Name).Order(StringComparer.Ordinal).ToArray()
                    }).ToArray(),
            });
        }
        return new()
        {
            ["type"] = "ls2_catalog",
            ["characters"] = characters,
            ["unavailable_characters"] = unavailable,
            ["acts"] = ModelDb.ActsByIndex.SelectMany((variants, index) => variants.Select(act => new
            {
                act = index + 1, variant = act.Id.Entry,
                encounters = act.AllEncounters.Select(e => new { id = e.Id.Entry, room = e.RoomType.ToString() })
                    .DistinctBy(e => e.id).OrderBy(e => e.id, StringComparer.Ordinal).ToArray()
            })).ToArray(),
            ["relics"] = ModelDb.AllRelics.Select(r => r.Id.Entry).Order(StringComparer.Ordinal).ToArray(),
            ["potions"] = ModelDb.AllPotions.Select(p => p.Id.Entry).Order(StringComparer.Ordinal).ToArray(),
            ["synthetic_potions"] = new[] { "FLEX_POTION", "DEXTERITY_POTION" },
        };
    }
}
