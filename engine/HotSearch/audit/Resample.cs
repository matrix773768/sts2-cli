using System.Text.Json;
using MegaCrit.Sts2.Core.Models;

namespace Sts2Headless;

public partial class RunSimulator
{
    internal Dictionary<string,object?> AuditWorld(JsonElement request){
        var pc=_runState?.Players[0].PlayerCombatState??throw new InvalidOperationException("no active combat");
        var pile=GetBackingList<CardModel>(pc.DrawPile,"_cards")??throw new InvalidOperationException("draw storage");
        string Token(CardModel c)=>c.Id.Entry+"#"+(c.IsUpgraded?1:0);
        var groups=pile.GroupBy(Token).ToArray();
        var counts=request.GetProperty("counts").Deserialize<Dictionary<string,int>>()!;
        if(groups.Length!=counts.Count || groups.Any(g=>counts.GetValueOrDefault(g.Key)!=g.Count()))
            throw new InvalidOperationException("native/public draw multiset");
        foreach(var g in groups){
            var descriptors=g.Select(c=>JsonSerializer.Serialize(new{cost=c.EnergyCost?.GetResolved(),
                enchant=c.Enchantment?.Id.Entry,ea=c.Enchantment?.Amount,affl=c.Affliction?.Id.Entry,aa=c.Affliction?.Amount,
                vars=c.DynamicVars.Values.ToDictionary(v=>v.Name,v=>v.BaseValue)}));
            if(descriptors.Distinct().Count()!=1)throw new NotSupportedException("native/heterogeneous type");
        }
        var cards=pile.OrderBy(Token,StringComparer.Ordinal).ToArray();
        var rng=new Random(request.GetProperty("seed").GetInt32());
        for(int i=cards.Length-1;i>0;i--){int j=rng.Next(i+1);(cards[i],cards[j])=(cards[j],cards[i]);}
        // Only permute the existing native instances. This consumes no native game RNG.
        pile.Clear();pile.AddRange(cards);
        return new(){["type"]="resampled",["size"]=cards.Length,["tokens"]=cards.Select(Token).ToArray()};
    }
}
