using CombatSolver.Engine.Common;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Cards;

namespace CombatSolver.Engine.InCombat.Simulation;

internal sealed class PileLaw
{
    internal Dictionary<string,int> Counts = [];
    internal List<string> Top = [], Bottom = [];
    internal string? Missing, OrderMissing;
    internal int Shuffles;
    internal bool ShuffleModifier;
    internal PileLaw Fork() => new() { Counts=new(Counts),Top=[..Top],Bottom=[..Bottom],
        Missing=Missing,OrderMissing=OrderMissing,Shuffles=Shuffles,ShuffleModifier=ShuffleModifier };
    internal object Export()=>new { counts=Counts.ToDictionary(),top=Top.ToArray(),bottom=Bottom.ToArray(),
        membership_gap=Missing,order_gap=OrderMissing,shuffles=Shuffles };
    internal void Add(string key,int delta)
    {
        int n=Counts.GetValueOrDefault(key)+delta;
        if(n<0){ Missing="untracked_zone_change";return; }
        if(n==0) Counts.Remove(key); else Counts[key]=n;
    }
    internal void Check(int size)
    {
        if(size==0){Counts.Clear();Top.Clear();Bottom.Clear();Missing=OrderMissing=null;}
        else if(Missing==null && Counts.Values.Sum()!=size){Missing="zone_count_mismatch";Top.Clear();Bottom.Clear();}
    }
    internal Dictionary<string,int>? Support(int size)
    {
        Check(size);
        if(Top.Count>0) return new() {[Top[0]]=1};
        if(Bottom.Count==size && size>0) return new(){[Bottom[0]]=1};
        if(Missing!=null || OrderMissing!=null) return null;
        var unknown=new Dictionary<string,int>(Counts);
        foreach(var key in Bottom)
        {
            if(!unknown.TryGetValue(key,out int n)) return null;
            if(n==1) unknown.Remove(key); else unknown[key]=n-1;
        }
        return unknown;
    }
}

internal sealed partial class SearchProbe
{
    internal TurnDrawTape? TurnDraw { get; init; }
    internal static bool PublicShuffle(CombatPredictionSimulator sim, Player player, List<PredictedCard> cards)
    {
        var tape=TurnDrawTape.Current;
        if(tape==null) return false;
        var pc=sim.State.GetPlayerCombatState(player);
        tape.Law.Check(pc.DrawPile.Cards.Count);
        foreach(var c in pc.DiscardPile.Cards) tape.Law.Add(TurnDrawTape.Type(c),1);
        tape.Law.Top.Clear();tape.Law.Bottom.Clear();tape.Law.Shuffles++;
        // Perfect Fit changes the post-shuffle order. Membership remains available.
        tape.Law.OrderMissing=pc.DiscardPile.Cards.Any(c=>c.Preview.Enchantment?.Id.Entry=="PERFECT_FIT") || tape.Law.ShuffleModifier
            ?"modified_shuffle_order":null;
        tape.Events.Add("shuffle");
        if (_current?.TurnDraw==null) return false;
        return true;
    }
}

internal sealed class TurnDrawTape(PileLaw law,string[] prefix) : IDisposable
{
    [ThreadStatic] internal static TurnDrawTape? Current;
    internal PileLaw Law=law.Fork();
    private string[] Transcript=>prefix;
    internal static IDisposable? Diagnostic(PileLaw? start)
    {
        if(Current is not {} previous || start==null) return null;
        Current=new TurnDrawTape(start,previous.Transcript){ModelEnemy=previous.ModelEnemy};
        return new DiagnosticScope(previous);
    }
    private sealed class DiagnosticScope(TurnDrawTape previous): IDisposable
    {
        public void Dispose()=>Current=previous;
    }
    internal int Used;
    internal bool Drawing;
    internal bool SuppressMoves,KnownGeneration,ModelEnemy;
    internal object? Paid,Strategic;
    internal Dictionary<string,int>? Options;
    internal List<string> Events=[];
    internal List<object> EnemyModels=[];
    internal Action<CombatPredictionSimulator, Player,int,int,bool,bool,bool>? AtC;
    internal TurnDrawTape Enter(){if(Current!=null) throw new InvalidOperationException("Nested pile observer");Current=this;return this;}
    public void Dispose()=>Current=null;
    internal static string Type(PredictedCard c)=>$"{c.Preview.Id.Entry}#{c.Preview.CurrentUpgradeLevel}";
    internal void Restore(PileLaw? origin)
    {
        if(origin==null)return;
        Law=origin.Fork();Used=0;Drawing=false;Events.Clear();EnemyModels.Clear();Strategic=null;
    }
    internal static void Removed(PileType from)
    {
        if(Current is {} t && from==PileType.Draw) {
            t.Law.Missing="hidden_removal";t.Law.Top.Clear();t.Law.Bottom.Clear();
        }
    }
    internal static int Insertion(Func<int> native,int size)
    {
        if(SearchProbe.IsPlanning && Current!=null)
            return size; // placeholder only; Move records any loss of positional constraints
        return native();
    }
    internal static void Move(PredictedCard c,PileType from,PileType to,CardPilePosition position)
    {
        if(Current is not {} t || t.SuppressMoves || from!=PileType.Draw && to!=PileType.Draw) return;
        var b=t.Law;
        if(from==PileType.Draw && to==PileType.Draw){b.OrderMissing="in_place_reorder";b.Top.Clear();b.Bottom.Clear();return;}
        if(from==PileType.Draw)
        {
            string key=Type(c); // the destination is a revealed zone
            bool atBottom=b.Missing==null && b.Counts.Values.Sum()==b.Bottom.Count;
            if(b.Top.Count!=0 && b.Top[0]==key)b.Top.RemoveAt(0);
            else if(atBottom && b.Bottom.Count>0 && b.Bottom[0]==key)b.Bottom.RemoveAt(0);
            else if(b.Top.Count>0 || !t.Drawing && b.Bottom.Contains(key)){b.Top.Clear();b.Bottom.Clear();b.OrderMissing="nonprefix_removal";}
            t.Drawing=false;b.Add(key,-1);t.Events.Add($"reveal:{to}:{key}");return;
        }
        if(from==PileType.None && !t.KnownGeneration){b.Missing="unobserved_generation";b.Top.Clear();b.Bottom.Clear();return;}
        string added=Type(c);
        b.Add(added,1);
        if(position==CardPilePosition.Top)b.Top.Insert(0,added);
        else if(position==CardPilePosition.Bottom)b.Bottom.Add(added);
        else if(b.Top.Count+b.Bottom.Count>0){b.Top.Clear();b.Bottom.Clear();b.OrderMissing="random_insertion_into_ordered_pile";}
        if(c.Preview.Enchantment?.Id.Entry=="PERFECT_FIT")b.ShuffleModifier=true;
        t.Events.Add($"insert:{position}:{added}");
    }
    internal void Draw(CombatPredictionSimulator sim,Player player,int remaining)
    {
        var pc=sim.State.GetPlayerCombatState(player);
        var pile=pc.DrawPile;
        Options=Law.Support(pile.Cards.Count);
        if(Options==null || Options.Count==0){SearchProbe.Stop("unknown_draw_law");return;}
        if(Used==prefix.Length)
        {
            var v=sim.State.GetCreature(player.Creature);
            Paid=new {energy=pc.Energy,hp=v.CurrentHp,block=v.Block,remaining,hand=pc.Hand.Cards.Select(Type).ToArray()};
            SearchProbe.Stop("public_draw");return;
        }
        var key=prefix[Used++];
        if(!Options.ContainsKey(key)) throw new InvalidOperationException("Outside public draw support");
        var copies=pile.Cards.Where(c=>Type(c)==key).ToArray();
        if(copies.Length==0 || Law.Missing==null && copies.Length!=Law.Counts.GetValueOrDefault(key)
            || copies.Select(CardChoiceSupport.ChoiceCardKey).Distinct().Count()!=1)
        {SearchProbe.Stop("unqualified_draw_instances");return;}
        pile.Remove(copies[0]);pile.Insert(0,copies[0]);
    }
}
internal sealed partial class SearchProbe
{
    internal static bool IsPlanning=>_current?.TurnDraw!=null;
}
