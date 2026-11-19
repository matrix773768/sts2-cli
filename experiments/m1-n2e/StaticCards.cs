using System.Text.Json;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;

namespace Sts2Headless;

public partial class RunSimulator
{
    internal object StaticCards(JsonElement command)
    {
        EnsureModelDbInitialized();
        return command.GetProperty("ids").EnumerateArray().Select(id =>
        {
            var model = ModelDb.GetById<CardModel>(new ModelId("CARD", id.GetString()!)).ToMutable();
            var variants = new List<object>();
            while (true)
            {
                variants.Add(new {
                    level = model.CurrentUpgradeLevel,
                    cost = model.EnergyCost.GetResolved(),
                    x_cost = model.EnergyCost.CostsX,
                    type = model.Type.ToString(),
                    rarity = model.Rarity.ToString(),
                    targeting = model.TargetType.ToString(),
                    keywords = model.Keywords.Select(x => x.ToString()).OrderBy(x => x, StringComparer.Ordinal).ToArray(),
                    variables = model.DynamicVars.Values.ToDictionary(v => v.Name, v => v.BaseValue)
                });
                if (!model.IsUpgradable) break;
                model.UpgradeInternal();
                model.FinalizeUpgradeInternal();
            }
            return new { id = model.Id.Entry, variants };
        }).ToArray();
    }
}
