using System.Runtime.InteropServices;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;
using MegaCrit.Sts2.Core.Combat;

// Compiled into a separate friend assembly inside the HotKernel load context.
// No old Solver types, seed, ordered hidden pile or RNG cross this interface.
public static class HotBackend
{
    private sealed record DrawWindow(Snapshot Parent,string[] Names,int Batch);
    public static object Open(string[] names,int[] counts,int batch)
    {
        CombatHotState state=default;
        var labels=new List<string>{""};
        for(int k=0;k<names.Length;k++)
            for(int j=0;j<counts[k];j++)
            {
                ushort uid=checked((ushort)labels.Count);
                state.Cards[state.DrawCount++].CardUid=uid;
                labels.Add(names[k]);
            }
        state.MaxHandSize=checked((byte)batch);
        var belief=DrawBelief.Create([],Enumerable.Range(1,state.DrawCount).Select(i=>(ushort)i),[]);
        return new DrawWindow(new Snapshot(in state,null,belief),labels.ToArray(),batch);
    }
    // Advance to the next unresolved public draw, for a qualified hook-free
    // interval only. Completed cards and end-turn phases belong to the caller.
    public static Dictionary<string,int>? Branch(object window,string[] tape)
    {
        var root=(DrawWindow)window;
        if(tape.Length==0 || tape.Length>=root.Batch)return null;
        var state=root.Parent.State;
        var belief=root.Parent.Belief;
        foreach(var token in tape)
        {
            var options=belief.Options();
            if(options.GroupBy(x=>root.Names[x.Instance]).Count()<2)return null;
            var ids=options.Where(x=>root.Names[x.Instance]==token).ToArray();
            if(ids.Length!=1)return null; // ambiguous public instance requires full solver
            ushort uid=ids[0].Instance;
            int index=state.DrawStart;
            while(index<state.TotalCardCount && state.Cards[index].CardUid!=uid)index++;
            if(index>=state.TotalCardCount)throw new InvalidOperationException("Lost public instance");
            var cards=MemoryMarshal.CreateSpan(ref state.Cards[state.DrawStart],state.DrawCount);
            var card=state.Cards[index];
            int offset=index-state.DrawStart;
            cards[..offset].CopyTo(cards.Slice(1,offset));cards[0]=card;
            if(!HotPiles.DrawTopToHand(ref state))return null;
            belief=belief.Draw(uid);
        }
        var support=belief.Options().GroupBy(o=>root.Names[o.Instance])
            .ToDictionary(g=>g.Key,g=>g.Count(),StringComparer.Ordinal);
        return support.Count>1?support:null;
    }
}
