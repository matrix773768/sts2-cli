using System.Text.Json;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;

internal sealed partial class Battle
{
    private static readonly HotCounterSlot[] PublicCounters=[
        HotCounterSlot.StatusCardsDrawnThisTurn, HotCounterSlot.ZeroCostAttackStartsThisTurn, HotCounterSlot.CardPlayStartsThisTurn,
        HotCounterSlot.AttackSkillStartsThisTurn, HotCounterSlot.AttackPlayStartsThisTurn, HotCounterSlot.SkillPlayStartsThisTurn,
        HotCounterSlot.PowerPlayStartsThisTurn, HotCounterSlot.CardsExhaustedThisTurn, HotCounterSlot.CardsDiscardedThisTurn,
        HotCounterSlot.EnergySpentThisTurn, HotCounterSlot.StarsGainedThisTurn, HotCounterSlot.NonHandDrawsThisTurn,
        HotCounterSlot.HasLostHpThisTurn, HotCounterSlot.WasDoomAppliedThisTurn, HotCounterSlot.AttacksPlayedThisTurn,
        HotCounterSlot.SkillsPlayedThisTurn, HotCounterSlot.CardsPlayedThisTurn, HotCounterSlot.PlayerCumulativeHpLost,
        HotCounterSlot.PlayerRecoveredHp, HotCounterSlot.OstyAttacksThisTurn, HotCounterSlot.SadnessGeneratedBefore,
        HotCounterSlot.BaseMaxEnergy, HotCounterSlot.BaseHandDraw, HotCounterSlot.CardBlockGainsThisTurn,
        HotCounterSlot.ShivPlaysFinishedThisTurn, HotCounterSlot.FirstInSeriesCardPlayStartsThisTurn, HotCounterSlot.HistoryCardsExhausted
    ];
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
        // Slots 0..26 are public play, movement, resource and damage totals plus base draw/energy.
        // Leave reserve slots zero. New counter kinds need their own information audit.
        foreach(var counter in PublicCounters)s.Counters[(int)counter]=w.Counters[(int)counter];
        for(int j=0;j<w.RosterCount;j++)s.ActiveEnemyRoster[s.RosterCount++]=w.ActiveEnemyRoster[j];
        for(int slot=0;slot<w.EnemyCount;slot++){
            var raw=w.Enemies[slot];var v=raw.Vital;
            var enemy=new HotEnemy{MonsterDefId=raw.MonsterDefId,CurrentMoveNode=raw.CurrentMoveNode,
                Vital=new(){CombatId=v.CombatId,SlotIdx=v.SlotIdx,CurrentHp=v.CurrentHp,MaxHp=v.MaxHp,Block=v.Block,
                    Flags=v.CurrentHp>0?HotCreatureFlags.ActiveInRoster|HotCreatureFlags.Alive:0}};
            // Each completed curse choice or respawn is public. No generic register copy.
            if(rules.Monsters[raw.MonsterDefId].Entry=="QUEEN")enemy.Flags|=raw.Flags&HotEnemyFlags.AmalgamDied;
            var history=announced[v.CombatId];
            var machine=rules.GetMonsterMachine(raw.MonsterDefId)!;
            if(machine.MonsterEntry=="BOWLBUG_ROCK" && machine.Nodes[raw.CurrentMoveNode].MoveId=="STUNNED"){
                // ImbalancedPower forces this public continuation after a fully blocked hit.
                enemy.AiRegs[3]=machine.FindNode("HEADBUTT_MOVE")+1;
            }
            if(machine.MonsterEntry=="TEST_SUBJECT"){
                // A respawn can interrupt a player action between two intent announcements.
                // Each new form applies its own public, permanent power.
                enemy.AiRegs[0]=HotCombatEngine.GetPowerAmountById(in w,rules,(byte)(slot+3),HotPowerId.NemesisPower)>0?2:
                    HotCombatEngine.GetPowerAmountById(in w,rules,(byte)(slot+3),HotPowerId.PainfulStabsPower)>0?1:0;
            }
            if(machine.MonsterEntry=="KNOWLEDGE_DEMON"){
                const string completed="CURSE_OF_KNOWLEDGE_MOVE";
                enemy.AiRegs[0]=history.SkipLast(1).Count(move=>machine.Nodes[move].MoveId==completed);
            }
            if(machine.MonsterEntry=="AEONGLASS"){
                // The same announced move increases both future strength and generated Wither upgrades.
                int intensifies=history.SkipLast(1).Count(move=>machine.Nodes[move].MoveId=="INCREASING_INTENSITY_MOVE");
                enemy.AiRegs[0]=enemy.AiRegs[1]=intensifies;
            }
            if(machine.MonsterEntry=="WATERFALL_GIANT"){
                string current=machine.Nodes[raw.CurrentMoveNode].MoveId;
                enemy.SteamPhase=current=="ABOUT_TO_BLOW_MOVE"?(byte)1:current=="EXPLODE_MOVE"?(byte)2:(byte)0;
                // PrepareSteamEruption latches the visible Steam amount when changing to EXPLODE.
                if(enemy.SteamPhase==2)enemy.AiRegs[1]=raw.AiRegs[1];
                int increase=rules.Monsters[raw.MonsterDefId].StaticInts?.GetValueOrDefault("PressureGunIncrease",5)??5;
                enemy.AiRegs[0]=history.SkipLast(1).Count(move=>machine.Nodes[move].MoveId=="PRESSURE_GUN_MOVE")*increase;
            }
            foreach(var move in history.TakeLast(8))enemy.RecentMoves[enemy.RecentMoveCount++]=checked((byte)move);
            foreach(var move in history)enemy.EverUsedMovesMask|=1UL<<move;
            s.Enemies[slot]=enemy;
            s.EnemyCount=(byte)Math.Max(s.EnemyCount,slot+1);s.NextCreatureId=Math.Max(s.NextCreatureId,v.CombatId+1);
        }
        for(int j=0;j<w.PowerCount;j++){
            var p=w.Powers[j];
            if(!VisiblePower(p.PowerDefId))continue;
            s.Powers[s.PowerCount++]=new(){PowerDefId=p.PowerDefId,OwnerSlot=p.OwnerSlot,Amount=p.Amount,AmountOnTurnStart=p.Amount,
                ApplierSlot=255,TargetSlot=rules.Powers[p.PowerDefId].PowerId==HotPowerId.SandpitPower?(byte)0:(byte)255,
                Flags=p.Flags&(HotPowerFlags.SkipNextDurationTick|HotPowerFlags.WasJustAppliedByEnemy)};
            if(rules.Powers[p.PowerDefId].PowerId==HotPowerId.WitheringPresencePower){
                // On this single-player root the visible enemy aura targets the player. Its countdown
                // starts at six, decreases on every publicly resolved play and resets on Wither generation.
                if(p.OwnerSlot<3 || p.Aux0<0 || p.Aux0>6)
                    throw new NotSupportedException("public/withering_presence_history");
                s.Powers[s.PowerCount-1].TargetSlot=0;
                s.Powers[s.PowerCount-1].Aux0=p.Aux0;
            }
            if(rules.Powers[p.PowerDefId].PowerId==HotPowerId.HexPower){
                var casters=new List<byte>();
                for(int i=0;i<s.EnemyCount;i++){
                    var e=s.Enemies[i];var m=rules.GetMonsterMachine(e.MonsterDefId)!;
                    if(e.Vital.CurrentHp>0 && announced[e.Vital.CombatId].SkipLast(1).Any(k=>m.Nodes[k].MoveId=="HEX"))
                        casters.Add((byte)(3+i));
                }
                if(casters.Count!=1)throw new NotSupportedException("public/ambiguous_hex_applier");
                s.Powers[s.PowerCount-1].ApplierSlot=casters[0];
            }
            // Facing follows the last public targeted play against a left/right enemy.
            if(rules.Powers[p.PowerDefId].PowerId==HotPowerId.SurroundedPower)s.Powers[s.PowerCount-1].Aux0=p.Aux0;
            if(rules.Powers[p.PowerDefId].PowerId==HotPowerId.DampenPower){
                // All surviving casters have announced DAMPEN_MOVE before the current turn.
                int mask=0;
                for(int i=0;i<s.EnemyCount;i++){
                    var e=s.Enemies[i];var m=rules.GetMonsterMachine(e.MonsterDefId)!;
                    if(e.Vital.CurrentHp>0 && announced[e.Vital.CombatId].SkipLast(1).Any(k=>m.Nodes[k].MoveId=="DAMPEN_MOVE"))mask|=1<<i;
                }
                s.Powers[s.PowerCount-1].Aux0=mask;
            }
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
    private sealed record Work(Snapshot Parent,HotAction Action,Prefix Prefix,double Mass,int Depth,int Memory=0,int Cursor=0);
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
        bool feedback=cmd.TryGetProperty("g2",out var g2Mode)&&g2Mode.GetBoolean();
        string style=cmd.TryGetProperty("style",out var field)?field.GetString()!:"light";
        if(style is not ("light" or "guard" or "build" or "end" or "setup"))throw new ArgumentException("policy/style");
        int ticket=0;
        var root=PublicRoot();
        var legal=Menu(root.State,root.Cold);
        var rootStamp=Stamp(Facts(root.State,root.Cold,root.Belief,legal,true));
        var results=new List<object>();
        int limit=cmd.GetProperty("limit").GetInt32();
        if(limit is <1 or >4096)throw new ArgumentOutOfRangeException(nameof(limit));
        foreach(int index in cmd.GetProperty("indices").EnumerateArray().Select(x=>x.GetInt32()).Distinct()){
            var first=menu[index];var leaves=new List<object>();var gaps=new Dictionary<string,double>();
            void Gap(string why,double mass)=>gaps[why]=gaps.GetValueOrDefault(why)+mass;
            var queue=new Queue<Work>();int steps=0,chances=0,choices=0;
            var policy=new Policy();
            if(legal.Contains(first))queue.Enqueue(new(root,first,Prefix.Empty,1,0,0,policy.Bind(0,rootStamp,Array.IndexOf(legal,first))));else Gap("projected_menu",1);
            while(queue.Count!=0 && steps<limit){
                var n=queue.Dequeue();var s=n.Parent.State;var side=n.Parent.Cold;
                var p=new Probe(rules,n.Parent.Belief,n.Prefix,n.Action.Kind.ToString(),Resolution.Public);
                var scratch=new HotExecScratch();
                try{
                    Probe.Current=p;
                    InfraCObserver.BeforeDraw=(in CombatHotState at,HotColdSidecar? c,HotRules r,int draw)=>{
                        leaves.Add(new{mass=n.Mass,cursor=n.Cursor,kind="C",facts=Facts(at,c,p.Belief,[],true),draw});throw new Cut();
                    };
                    steps++;
                    var result=HotCombatEngine.Step(ref s,ref side,rules,scratch,n.Action);
                    if(!result.Executed||result.NeedsChoice)throw new NotSupportedException("step/rejected");
                    p.RequireConsumed();

                    p.Belief.Validate(in s,false);
                    if(s.TerminalOutcome!=HotCombatOutcome.Ongoing)
                        leaves.Add(new{mass=n.Mass,cursor=n.Cursor,kind=s.TerminalOutcome.ToString(),hp=s.Player.CurrentHp,max_hp=s.Player.MaxHp,gold=s.Gold});
                    else if(n.Depth>=15)Gap("depth",n.Mass);
                    else{
                        var child=new Snapshot(in s,side,p.Belief);
                        var options=Menu(s,side);
                        var facts=Facts(s,side,p.Belief,options,true);
                        int next=feedback?Program.Score(n.Memory,++ticket,facts,null,options.Length):
                            Array.IndexOf(options,stopAfterFirst?HotAction.EndTurn():Tactical(child,style,facts));
                        if(next<0)throw new NotSupportedException("policy/menu");
                        int cursor=policy.Bind(n.Cursor,Stamp(facts),next);
                        queue.Enqueue(new(child,options[next],Prefix.Empty,n.Mass,n.Depth+1,feedback?ticket:0,cursor));
                    }
                }catch(Cut){}
                catch(Boundary b) when(b.Status==StepStatus.NeedsChance){
                    chances++;var ev=p.Events[^1];
                    foreach(var group in ev.Options.GroupBy(o=>o.Observation)){
                        var opt=group.First();queue.Enqueue(n with{Prefix=n.Prefix.AddDraw(ev,opt.Instance),Mass=n.Mass*group.Sum(o=>o.Probability)});
                    }
                }catch(Boundary b) when(b.Status==StepStatus.NeedsChoice){
                    choices++;var ev=p.Events[^1];int selected=0,memory=n.Memory;
                    var options=OptionNames(s,ev);var facts=Facts(s,side,p.Belief,[],true);
                    var choice=new{kind=ev.Phase,options};
                    if(style=="setup")selected=PickForSetup(s,ev);
                    if(feedback){
                        selected=Program.Score(memory,++ticket,facts,choice,options.Length);
                        memory=ticket;
                    }
                    queue.Enqueue(n with{Prefix=n.Prefix.AddChoice(ev,ev.Choices[selected]),Memory=memory,Cursor=policy.Bind(n.Cursor,Stamp(facts,choice),selected)});
                }catch(Boundary b){Gap(b.Point+"/"+b.Message,n.Mass);}
                catch(Exception e) when(e is NotSupportedException or HotCapacityExceededException or InvalidOperationException){
                    Gap(e.Message,n.Mass);
                }finally{Probe.Current=null;InfraCObserver.BeforeDraw=null;HotCombatEngine.ClearPendingChoiceUidFilters();}
            }
            if(queue.Count!=0)Gap("budget",queue.Sum(x=>x.Mass));
            results.Add(new{index,steps,chances,choices,leaves,gaps,policy=policy.Edges});
        }
        return results;
    }
}
