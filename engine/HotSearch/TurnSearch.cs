using System.Text.Json;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;

internal sealed partial class Battle
{
    // Rebuild from the public zones and transcript. The search never clones the live root.
    private Snapshot PublicRoot()
    {
        var w=world;
        if(w.OrbCount+w.ArrowCount!=0 || w.PlayCount!=0)throw new NotSupportedException("public/special_zone");
        var s=new CombatHotState{
            PlayerTurnNumber=w.PlayerTurnNumber,RoundNumber=w.RoundNumber,Energy=w.Energy,Stars=w.Stars,Gold=w.Gold,
            MaxHandSize=w.MaxHandSize,PotionSlotCount=w.PotionSlotCount,PlayerPhase=1,CurrentSide=HotCombatSide.Player,
            CombatFlags=HotCombatFlags.IsInProgress|HotCombatFlags.PlayerHooksActive,NextCardUid=1,NextCreatureId=1,
            Player=new(){CombatId=0,SlotIdx=0,CurrentHp=w.Player.CurrentHp,MaxHp=w.Player.MaxHp,Block=w.Player.Block,
                Flags=HotCreatureFlags.ActiveInRoster|HotCreatureFlags.Alive|HotCreatureFlags.IsPlayer}};
        // Each named counter is a public action/resource history aggregate or the public base draw/energy.
        s.DrawNextTurn=w.DrawNextTurn;s.HistoryFinishedPlays=w.HistoryFinishedPlays;s.HistoryEtherealPlays=w.HistoryEtherealPlays;
        s.HistoryUnblockedHitsReceived=w.HistoryUnblockedHitsReceived;s.HistoryCardsDrawn=w.HistoryCardsDrawn;s.HistoryCardsGenerated=w.HistoryCardsGenerated;
        s.ShuffleEventCount=w.ShuffleEventCount;s.AngerCopiesGenerated=w.AngerCopiesGenerated;
        foreach(var k in Enum.GetValues<HotCounterSlot>())
            s.Counters[(int)k]=w.Counters[(int)k];
        for(int j=0;j<w.RosterCount;j++)s.ActiveEnemyRoster[s.RosterCount++]=w.ActiveEnemyRoster[j];
        for(int slot=0;slot<w.EnemyCount;slot++){
            var raw=w.Enemies[slot];var v=raw.Vital;
            var enemy=new HotEnemy{MonsterDefId=raw.MonsterDefId,CurrentMoveNode=raw.CurrentMoveNode,
                Vital=new(){CombatId=v.CombatId,SlotIdx=v.SlotIdx,CurrentHp=v.CurrentHp,MaxHp=v.MaxHp,Block=v.Block,
                    Flags=v.CurrentHp>0?HotCreatureFlags.ActiveInRoster|HotCreatureFlags.Alive:0}};
            if(rules.Monsters[raw.MonsterDefId].Entry is "KNOWLEDGE_DEMON" or "TEST_SUBJECT")enemy.AiRegs[0]=raw.AiRegs[0];
            if(rules.Monsters[raw.MonsterDefId].Entry=="QUEEN")enemy.Flags|=raw.Flags&HotEnemyFlags.AmalgamDied;
            var history=announced[v.CombatId];
            foreach(var move in history.TakeLast(8))enemy.RecentMoves[enemy.RecentMoveCount++]=checked((byte)move);
            foreach(var move in history)enemy.EverUsedMovesMask|=1UL<<move;
            s.Enemies[slot]=enemy;
            s.EnemyCount=(byte)Math.Max(s.EnemyCount,slot+1);s.NextCreatureId=Math.Max(s.NextCreatureId,v.CombatId+1);
        }
        for(int j=0;j<w.PowerCount;j++){
            var p=w.Powers[j];
            if(!VisiblePower(p.PowerDefId))continue;
            s.Powers[s.PowerCount++]=new(){PowerDefId=p.PowerDefId,OwnerSlot=p.OwnerSlot,Amount=p.Amount,AmountOnTurnStart=p.Amount,
                ApplierSlot=255,TargetSlot=255};
        }
        void Visible(HotPileKind pile){
            foreach(var raw in Zone(w,pile)){
                var c=PublicCard(raw);c.CardUid=s.NextCardUid++;
                if(raw.CostModCount>4)throw new NotSupportedException("public/cost_overflow");
                s.Cards[s.TotalCardCount]=c;
                if(pile==HotPileKind.Hand)s.HandCount++;else if(pile==HotPileKind.Discard)s.DiscardCount++;else s.ExhaustCount++;
            }
        }
        Visible(HotPileKind.Hand);
        ushort[] Hidden(IEnumerable<ushort> ids){
            var result=new List<ushort>();
            foreach(var id in ids){
                var c=declaredCards[id];c.CardUid=s.NextCardUid++;
                if(c.CostModCount>4)throw new NotSupportedException("public/cost_overflow");
                s.Cards[s.TotalCardCount]=c;s.DrawCount++;result.Add(c.CardUid);
            }
            return result.ToArray();
        }
        var top=Hidden(law.Top);var bag=Hidden(law.Unknown.OrderBy(Label,StringComparer.Ordinal).ThenBy(Descriptor,StringComparer.Ordinal));var bottom=Hidden(law.Bottom);
        Visible(HotPileKind.Discard);Visible(HotPileKind.Exhaust);
        s.ActiveHookMask=HotCombatEngine.RecomputeActiveHookMask(in s,rules);
        var belief=new DrawBelief(top,bag,bottom,law.Generation){Counts=law.Counts};belief.Validate(in s,false);
        return new Snapshot(in s,null,belief);
    }
    private sealed class Cut:Exception;
    private sealed record Work(Snapshot Parent,HotAction Action,Prefix Prefix,double Mass,int Depth,int Memory=0);
    private HotAction Continue(Snapshot n)
    {
        var s=n.State;
        var actions=Menu(s,n.Cold);
        return actions.OrderByDescending(a=>{
            if(a.Kind!=HotActionKind.PlayCard)return -1d;
            var c=s.Cards[a.SlotOrHandIdx];var d=rules.Cards[c.CardDefId];
            double hit=d.GetDamage(c.UpgradeLevel,0)*Math.Max(1,d.GetHits(c.UpgradeLevel));
            return hit+d.GetBlock(c.UpgradeLevel,0)*0.65+(a.TargetEnemySlot<0?0:1d/(1+s.Enemies[a.TargetEnemySlot].Vital.CurrentHp));
        }).First();
    }
    public int Continuation(){
        int index=Array.IndexOf(menu,Continue(PublicRoot()));
        return index>=0?index:throw new NotSupportedException("continuation/menu");
    }
    public object Search(JsonElement cmd)
    {
        if(prompt!=null)throw new InvalidOperationException("search/prompt");
        bool stopAfterFirst=cmd.TryGetProperty("then_end",out var mode) && mode.GetBoolean();
        bool feedback=cmd.TryGetProperty("g2",out var policy)&&policy.GetBoolean();
        int ticket=0;
        var root=PublicRoot();
        var legal=Menu(root.State,root.Cold);
        var results=new List<object>();
        int limit=cmd.GetProperty("limit").GetInt32();
        if(limit is <1 or >4096)throw new ArgumentOutOfRangeException(nameof(limit));
        foreach(int index in cmd.GetProperty("indices").EnumerateArray().Select(x=>x.GetInt32()).Distinct()){
            var first=menu[index];var leaves=new List<object>();var gaps=new Dictionary<string,double>();
            void Gap(string why,double mass)=>gaps[why]=gaps.GetValueOrDefault(why)+mass;
            var queue=new Queue<Work>();int steps=0,chances=0,choices=0;
            if(legal.Contains(first))queue.Enqueue(new(root,first,Prefix.Empty,1,0));else Gap("projected_menu",1);
            while(queue.Count!=0 && steps<limit){
                var n=queue.Dequeue();var s=n.Parent.State;var side=n.Parent.Cold;
                var p=new Probe(rules,n.Parent.Belief,n.Prefix,n.Action.Kind.ToString(),Resolution.Public);
                var scratch=new HotExecScratch();
                try{
                    Probe.Current=p;
                    InfraCObserver.BeforeDraw=(in CombatHotState at,HotColdSidecar? c,HotRules r,int draw)=>{
                        leaves.Add(new{mass=n.Mass,kind="C",facts=Facts(at,c,p.Belief,[],true),draw});throw new Cut();
                    };
                    steps++;
                    var result=HotCombatEngine.Step(ref s,ref side,rules,scratch,n.Action);
                    if(!result.Executed||result.NeedsChoice)throw new NotSupportedException("step/rejected");
                    p.RequireConsumed();

                    p.Belief.Validate(in s,false);
                    if(s.TerminalOutcome!=HotCombatOutcome.Ongoing)
                        leaves.Add(new{mass=n.Mass,kind=s.TerminalOutcome.ToString(),hp=s.Player.CurrentHp,max_hp=s.Player.MaxHp,gold=s.Gold});
                    else if(n.Depth>=15)Gap("depth",n.Mass);
                    else{
                        var child=new Snapshot(in s,side,p.Belief);
                        if(feedback){
                            var options=Menu(s,side);
                            int next=Program.Score(n.Memory,++ticket,Facts(s,side,p.Belief,options,true),null,options.Length);
                            queue.Enqueue(new(child,options[next],Prefix.Empty,n.Mass,n.Depth+1,ticket));
                        }else queue.Enqueue(new(child,stopAfterFirst?HotAction.EndTurn():Continue(child),Prefix.Empty,n.Mass,n.Depth+1));
                    }
                }catch(Cut){}
                catch(Boundary b) when(b.Status==StepStatus.NeedsChance){
                    chances++;var ev=p.Events[^1];
                    foreach(var group in ev.Options.GroupBy(o=>o.Observation)){
                        var opt=group.First();queue.Enqueue(n with{Prefix=n.Prefix.AddDraw(ev,opt.Instance),Mass=n.Mass*group.Sum(o=>o.Probability)});
                    }
                }catch(Boundary b) when(b.Status==StepStatus.NeedsChoice){
                    choices++;var ev=p.Events[^1];int selected=0,memory=n.Memory;
                    if(feedback){
                        var options=OptionNames(s,ev);
                        selected=Program.Score(memory,++ticket,Facts(s,side,p.Belief,[],true),new{kind=ev.Phase,options},options.Length);
                        memory=ticket;
                    }
                    queue.Enqueue(n with{Prefix=n.Prefix.AddChoice(ev,ev.Choices[selected]),Memory=memory});
                }catch(Boundary b){Gap(b.Point+"/"+b.Message,n.Mass);}
                catch(Exception e) when(e is NotSupportedException or HotCapacityExceededException or InvalidOperationException){
                    Gap(e.Message,n.Mass);
                }finally{Probe.Current=null;InfraCObserver.BeforeDraw=null;HotCombatEngine.ClearPendingChoiceUidFilters();}
            }
            if(queue.Count!=0)Gap("budget",queue.Sum(x=>x.Mass));
            results.Add(new{index,steps,chances,choices,leaves,gaps});
        }
        return results;
    }
}
