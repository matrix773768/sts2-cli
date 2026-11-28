using CombatSolver.HotKernel;

namespace CombatSolver.HotDraw;

internal sealed partial class Probe
{
    internal bool PublicMode => resolution==Resolution.Public;
    [ThreadStatic] internal static Action<HotCard>? Published;
    private ushort staged;
    private string TypeOf(HotCard c)=>rules.Cards[c.CardDefId].Entry+"#"+c.UpgradeLevel;
    private Dictionary<string,int>? membership;
    private void Count(HotCard card,int delta)
    {
        membership??=new Dictionary<string,int>(belief.Counts??throw new InvalidOperationException("public counts missing"));
        string key=TypeOf(card);
        int after=membership.GetValueOrDefault(key)+delta;
        if(after<0)Reject("unobserved_card_change",key);
        if(after==0)membership.Remove(key);else membership[key]=after;
        Belief=Belief with{Counts=membership};
    }
    private void ResetMembership(in CombatHotState s){
        membership=new();
        for(int i=s.DiscardStart;i<s.ExhaustStart;i++)Count(s.Cards[i],1);
        Belief=Belief with{Counts=membership};
    }
    internal void Autoplay(ref CombatHotState s,HotColdSidecar? cold,HotExecScratch scratch,int remaining)
    {
        BeforeDraw(ref s,cold,scratch,false,remaining,"autoplay_to_play");
        staged=s.Cards[s.DrawStart].CardUid;
    }
    private bool ConsumeStaged(ushort uid,HotPileKind destination)
    {
        if(staged==0 || uid!=staged || destination!=HotPileKind.Play)return false;
        staged=0;return true;
    }
    private bool randomInsert;
    internal bool BeginRandomInsert()
    {
        if(Belief.Top.Length+Belief.Bottom.Length!=0)
            Reject("random_insert_known_positions","AddCard");
        randomInsert=true;
        return PublicMode;
    }
    internal void Added(in CombatHotState state,in HotCard card,HotPileKind destination,int offset)
    {
        if(destination==HotPileKind.Draw){
            if(randomInsert)
                Belief=Belief with{Unknown=Belief.Unknown.Append(card.CardUid).Order().ToArray()};
            else{
                if(offset!=0 && offset!=state.DrawCount)Reject("interior_generated_insert","AddCard");
                Belief=Belief.Insert(card.CardUid,offset==0);
            }
            Count(card,1);
            randomInsert=false;
        }
        Published?.Invoke(card);
    }

    // Integrate the actual float selection over the 2^53 equiprobable NextDouble outputs.
    // Zero-weight bins can receive the exactly-zero roll at the lower endpoint.
    internal int MonsterChoice(ReadOnlySpan<float> source,float total,string phase)
    {
        var weights=source.ToArray();
        const long size=1L<<53;
        int Which(long word){
            float roll=(float)((word/(double)size)*total);
            for(int i=0;i<weights.Length;i++)if((roll-=weights[i])<=0)return i;
            return Array.FindLastIndex(weights,w=>w>0) is var last && last>=0?last:0;
        }
        var options=new List<OutcomeOption>();
        long lower=0;
        for(int i=0;i<weights.Length && lower<size;i++){
            long lo=lower,hi=size;
            while(lo<hi){long mid=lo+((hi-lo)>>1);if(Which(mid)<=i)lo=mid+1;else hi=mid;}
            if(lo>lower)options.Add(new OutcomeOption(checked((ushort)(i+1)),1){Weight=(lo-lower)/(double)size});
            lower=lo;
        }
        if(options.Count==1)return options[0].Instance-1;
        var ev=new StepEvent(Events.Count,EventKind.Monster,actionSource,phase,0,0,"announced_move",options.ToArray(),[]);
        if(drawCursor==prefix.Draws.Length || prefix.Draws[drawCursor].Address!=ev.Address){
            RequireConsumed();Events.Add(ev);throw new Boundary(StepStatus.NeedsChance,"monster_move",phase);
        }
        var selected=prefix.Draws[drawCursor++].Instance;
        if(!options.Any(o=>o.Instance==selected))throw new InvalidOperationException("monster support changed");
        Events.Add(ev with{Result=selected});return selected-1;
    }
}
