using CombatSolver.HotDraw;
using CombatSolver.HotKernel;

internal sealed partial class Battle
{
    private sealed record Checkpoint(CombatHotState World,HotColdSidecar? Cold,DrawBelief Law,
        Dictionary<ushort,(ushort Def,byte Up)> Labels,Dictionary<ushort,HotCard> Cards,Dictionary<uint,List<short>> History,int Turn,int Decisions);
    private Checkpoint? checkpoint;
    public object Save()
    {
        if(prompt!=null || world.TerminalOutcome!=HotCombatOutcome.Ongoing)throw new InvalidOperationException("checkpoint/unstable");
        checkpoint=new(world,cold,law,new(labels),new(declaredCards),announced.ToDictionary(k=>k.Key,k=>k.Value.ToList()),recordedTurn,decisions);
        return new{turn=recordedTurn};
    }
    public object Restore(int? seed,int? auditRng=null)
    {
        var c=checkpoint??throw new InvalidOperationException("checkpoint/missing");
        world=c.World;cold=c.Cold;law=c.Law;recordedTurn=c.Turn;decisions=c.Decisions;
        observedC=null;prompt=null;transcript=Prefix.Empty;
        declaredCards.Clear();foreach(var pair in c.Cards)declaredCards.Add(pair.Key,pair.Value);
        labels.Clear();foreach(var pair in c.Labels)labels.Add(pair.Key,pair.Value);
        announced.Clear();foreach(var pair in c.History)announced.Add(pair.Key,pair.Value.ToList());
        if(seed.HasValue){
            if(law.Top.Length+law.Bottom.Length!=0 || law.Unknown.Length<2)
                throw new NotSupportedException("world/nonexchangeable_tail");
            var cards=Zone(world,HotPileKind.Draw).OrderBy(Token,StringComparer.Ordinal).ToArray();
            foreach(var group in cards.GroupBy(Token)){
                int i=Array.FindIndex(cards,x=>x.CardUid==group.First().CardUid);
                int pos=HotCombatEngine.FindCardIndexByUidAnyPile(in world,cards[i].CardUid);
                foreach(var item in group.Skip(1)){
                    int other=HotCombatEngine.FindCardIndexByUidAnyPile(in world,item.CardUid);
                    if(!HotCombatEngine.EquivalentResearchDraw(in world,cold,pos,other))
                        throw new NotSupportedException("world/instance_law");
                }
            }
            // CORE-5E changes only the exchangeable tail. All future real RNG streams stay paired.
            var rng=new Random(seed.Value);
            for(int i=cards.Length-1;i>0;i--){int j=rng.Next(i+1);(cards[i],cards[j])=(cards[j],cards[i]);}
            for(int i=0;i<cards.Length;i++)world.Cards[world.DrawStart+i]=cards[i];
            law.Validate(in world,true);
        }
        if(auditRng.HasValue){
            ulong mixer=(uint)auditRng.Value;
            for(int i=0;i<10;i++)world.Rng[i]=HotRng.CreateFromSeed(HotRng.Splitmix64(ref mixer));
            // A bijection on hidden handles preserves the declared public descriptors.
            var old=law.Unknown.ToArray();var rev=old.Reverse().ToArray();
            var rename=old.Zip(rev).ToDictionary(x=>x.First,x=>x.Second);
            for(int i=world.DrawStart;i<world.DiscardStart;i++){
                ref var card=ref world.Cards[i];
                if(rename.TryGetValue(card.CardUid,out var id))card.CardUid=id;
            }
            for(int i=0;i<old.Length;i++){
                labels[rev[i]]=c.Labels[old[i]];
                declaredCards[rev[i]]=c.Cards[old[i]];
            }
            for(int i=0;i<world.EnemyCount;i++)world.Enemies[i].AiRegs[3]^=17;
        }
        return View();
    }
}
