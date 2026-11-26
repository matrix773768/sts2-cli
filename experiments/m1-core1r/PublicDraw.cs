using CombatSolver.Engine.Common;
using MegaCrit.Sts2.Core.Entities.Players;

namespace CombatSolver.Engine.InCombat.Simulation;

internal sealed partial class SearchProbe
{
    internal TurnDrawTape? TurnDraw { get; init; }
    internal static bool PublicShuffle(CombatPredictionSimulator sim, Player player, List<PredictedCard> cards)
    {
        if (_current?.TurnDraw is not { } tape) return false;
        var pc = sim.State.GetPlayerCombatState(player);
        if (!pc.DrawPile.IsEmpty || cards.Any(c => c.Preview.Enchantment != null))
            Stop("unqualified_shuffle");
        tape.Bag = cards.GroupBy(TurnDrawTape.Type).ToDictionary(g => g.Key,g => g.Count());
        cards.Sort((a,b) => string.CompareOrdinal(CardChoiceSupport.ChoiceCardKey(a),CardChoiceSupport.ChoiceCardKey(b)));
        return true;
    }
}

internal sealed class TurnDrawTape(Dictionary<string,int>? bag, string[] prefix)
{
    internal Dictionary<string,int>? Bag = bag == null ? null : new(bag);
    internal int Used;
    internal object? Paid;
    internal static string Type(PredictedCard c) => $"{c.Preview.Id.Entry}#{c.Preview.CurrentUpgradeLevel}";

    internal void Draw(CombatPredictionSimulator sim, Player player, int remaining)
    {
        var pc=sim.State.GetPlayerCombatState(player);
        var pile=pc.DrawPile;
        if (Bag == null || Bag.Values.Sum()!=pile.Cards.Count)
        {
            SearchProbe.Stop("unqualified_public_belief");
            return;
        }
        if (Used==prefix.Length)
        {
            var v=sim.State.GetCreature(player.Creature);
            var combat=(SimulatedCombatState)sim.State.CombatState;
            Paid=new { energy=pc.Energy,hp=v.CurrentHp,block=v.Block,remaining,round=combat.RoundNumber,
                hand=pc.Hand.Cards.Select(Type).ToArray(),
                enemies=combat.KnownEnemies.Select(e=>new {species=e.Monster?.Id.Entry,
                    hp=sim.State.GetCreature(e).CurrentHp,block=sim.State.GetCreature(e).Block}).ToArray() };
            SearchProbe.Stop("public_draw");
            return;
        }
        var key=prefix[Used++];
        if (!Bag.TryGetValue(key,out int count)) throw new InvalidOperationException("Draw outside public support");
        // Lookup the requested public type only. Hidden positions never determine the option or its mass.
        var copies=pile.Cards.Where(c=>Type(c)==key).ToArray();
        if (copies.Length!=count || copies.Select(CardChoiceSupport.ChoiceCardKey).Distinct().Count()!=1 ||
            copies.Any(c=>c.Preview.Enchantment!=null || c.Preview.Affliction!=null))
        {
            SearchProbe.Stop("unqualified_draw_instances");
            return;
        }
        if (count==1) Bag.Remove(key); else Bag[key]=count-1;
        pile.Remove(copies[0]);
        pile.Insert(0,copies[0]);
    }
}
