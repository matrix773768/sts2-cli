using System.Text.Json;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.MonsterMoves.MonsterMoveStateMachine;

internal sealed partial class Battle
{
    private readonly HotRules rules;
    private readonly JsonElement deck;
    private readonly Dictionary<(string,string),string[]> intents=new();
    private readonly Dictionary<ushort,bool> visiblePowers=new();
    private bool VisiblePower(ushort id){
        if(!visiblePowers.TryGetValue(id,out var show))visiblePowers[id]=show=ModelDb.GetById<PowerModel>(new ModelId("POWER",rules.Powers[id].Entry)).IsVisible;
        return show;
    }
    private readonly Dictionary<ushort,(ushort Def,byte Up)> labels=new();
    private readonly Dictionary<ushort,HotCard> declaredCards=new();
    private CombatHotState world;
    private static HotCard PublicCard(HotCard c)=>new(){
        CardDefId=c.CardDefId,UpgradeLevel=c.UpgradeLevel,BaseEnergyCost=c.BaseEnergyCost,BaseStarCost=c.BaseStarCost,
        DampenOrigUpg=c.DampenOrigUpg,BaseReplayCount=c.BaseReplayCount,ExtraReplayThisTurn=c.ExtraReplayThisTurn,LocalKeywordsMask=c.LocalKeywordsMask,
        Flags=c.Flags&(HotCardFlags.CostsX|HotCardFlags.HasStarCostX|HotCardFlags.HasDeckVersion|HotCardFlags.SingleTurnRetain|
            HotCardFlags.IsSlyThisTurn|HotCardFlags.ExhaustOnNextPlay|HotCardFlags.ReturnToHandNextTurn|HotCardFlags.FetchPlayedThisTurn),
        CostModCount=c.CostModCount,EnergyCostMods=c.EnergyCostMods,TempStarCostPacked=c.TempStarCostPacked,
        EnchId=c.EnchId,EnchAmt=c.EnchAmt,AfflId=c.AfflId,AfflAmt=c.AfflAmt,Var0Delta=c.Var0Delta,Var1Delta=c.Var1Delta
    };
    private void Publish(HotCard c){
        labels[c.CardUid]=(c.CardDefId,c.UpgradeLevel);
        declaredCards[c.CardUid]=PublicCard(c);
    }
    private string Descriptor(ushort id){
        var c=declaredCards[id];
        return Convert.ToHexString(System.Runtime.InteropServices.MemoryMarshal.AsBytes(new ReadOnlySpan<HotCard>(in c)));
    }
    private HotColdSidecar? cold;
    private DrawBelief law;
    private HotAction[] menu=[];
    private HotAction waiting;
    private Prefix transcript=Prefix.Empty;
    private StepEvent? prompt;
    private long actualSteps;
    private int decisions;
    private object? observedC;
    private readonly Dictionary<uint,List<short>> announced=new();
    private int recordedTurn;

    public Battle(JsonElement spec)
    {
        var live=CombatManager.Instance.DebugOnlyGetState()!;
        foreach(var creature in live.Enemies){
            var monster=creature.Monster!;
            foreach(var move in monster.MoveStateMachine!.States.Values.OfType<MoveState>())
                intents[(monster.Id.Entry,move.Id)]=move.Intents.Select(i=>i.IntentType.ToString()).ToArray();
        }
        var root=HotRootBuilder.BuildFromLive(live);
        rules=root.Rules; world=root.RootState; cold=root.RootCold;
        if(!rules.CoverageManifest.IsRootFullySupported)
            throw new NotSupportedException(string.Join("/",rules.CoverageManifest.UnsupportedReasons));
        deck=spec.GetProperty("deck").Clone();
        if(rules.RootPets.Length!=0 || rules.ActiveRelics.Length!=0 ||
            spec.GetProperty("potions").EnumerateArray().Any(x=>x.ValueKind!=JsonValueKind.Null))
            throw new NotSupportedException("public/resource_hooks");
        var declared=deck.EnumerateArray().Select(c=>c.GetProperty("id").GetString()+"#"+c.GetProperty("upgrade").GetInt32()).Order().ToArray();
        // Private identities bind observable events only. No private position or UID is a policy feature.
        var imported=new List<string>();
        var unknown=new List<ushort>();
        for(int i=0;i<world.TotalCardCount;i++){
            var c=world.Cards[i];labels.Add(c.CardUid,(c.CardDefId,c.UpgradeLevel));
            imported.Add(Token(c));
            if(i>=world.DrawStart && i<world.DiscardStart)unknown.Add(c.CardUid);
        }
        if(!declared.SequenceEqual(imported.Order()) || world.PlayerTurnNumber!=1 || world.DiscardCount+world.ExhaustCount!=0)
            throw new NotSupportedException("opening/public_membership");
        var counts=deck.EnumerateArray().Select(c=>c.GetProperty("id").GetString()+"#"+c.GetProperty("upgrade").GetInt32())
            .GroupBy(k=>k).ToDictionary(g=>g.Key,g=>g.Count());
        foreach(var c in Zone(world,HotPileKind.Hand)){string key=Token(c);if(--counts[key]==0)counts.Remove(key);}
        CombatHotState rootScratch=default;
        foreach(var uid in unknown){
            var c=labels[uid];
            var prototype=HotCombatEngine.CreateFreshCard(ref rootScratch,rules.Cards[c.Def],c.Up!=0);
            // Before the opening draw, Vital Spark afflicts every skill entering combat.
            if(rules.Cards[c.Def].Type.ToString()=="Skill"){
                foreach(var enemy in ZonePowers(world,HotPowerId.VitalSparkPower)){
                    prototype.AfflId=rules.GetAfflictionDefId(HotAfflictionId.Tainted);
                    prototype.AfflAmt=(short)Math.Clamp(enemy,0,byte.MaxValue);
                }
            }
            prototype.Flags|=HotCardFlags.HasDeckVersion;declaredCards[uid]=PublicCard(prototype);
            if((prototype.LocalKeywordsMask&HotCardKeywordMask.Innate)!=0)throw new NotSupportedException("opening/innate_overflow");
        }
        law=DrawBelief.Create([],unknown,[]) with{Counts=counts};
        Remember();
    }

    private IEnumerable<int> ZonePowers(CombatHotState s,HotPowerId power){
        for(int i=0;i<s.PowerCount;i++){
            var p=s.Powers[i];
            if(p.Amount>0 && rules.Powers[p.PowerDefId].PowerId==power)yield return p.Amount;
        }
    }
    private string Token(HotCard card)=>rules.Cards[card.CardDefId].Entry+"#"+card.UpgradeLevel;
    private string Label(ushort uid){var c=labels[uid];return rules.Cards[c.Def].Entry+"#"+c.Up;}
    private void Remember()
    {
        foreach(var pile in new[]{HotPileKind.Hand,HotPileKind.Discard,HotPileKind.Exhaust})
            foreach(var c in Zone(world,pile))Publish(c);
        if(recordedTurn==world.PlayerTurnNumber)return;
        recordedTurn=world.PlayerTurnNumber;
        for(int i=0;i<world.EnemyCount;i++){
            var e=world.Enemies[i];
            if(!announced.TryGetValue(e.Vital.CombatId,out var history))announced[e.Vital.CombatId]=history=[];
            history.Add(e.CurrentMoveNode);
        }
    }
    private static HotCard[] Zone(CombatHotState s,HotPileKind pile){
        int start=HotPiles.ZoneStart(in s,pile),count=HotPiles.ZoneCount(in s,pile);
        var cards=new HotCard[count];
        for(int i=0;i<count;i++)cards[i]=s.Cards[start+i];
        return cards;
    }
    private MegaCrit.Sts2.Core.Entities.Cards.TargetType Target(CombatHotState s,HotAction a){
        var c=s.Cards[a.SlotOrHandIdx];return HotCombatEngine.GetEffectiveCardTargetType(in s,in c,rules.Cards[c.CardDefId],rules);
    }
    private HotAction[] Menu(CombatHotState s, HotColdSidecar? side){
        var buffer=new HotAction[HotLimits.MaxCards*(HotLimits.MaxEnemies+1)+1];
        int count=HotCombatEngine.EnumerateLegalActions(in s,side,rules,buffer);
        return buffer[..count].Where(a=>a.Kind!=HotActionKind.PlayCard || Target(s,a)!=MegaCrit.Sts2.Core.Entities.Cards.TargetType.AnyAlly).ToArray();
    }
    public object View(){
        bool terminal=world.TerminalOutcome!=HotCombatOutcome.Ongoing;
        menu=terminal?[]:Menu(world,cold);
        var facts=Facts(world,cold,law,menu);
        return new{status=terminal?world.TerminalOutcome.ToString():"active", facts,view=Stamp(facts),
            observed_c=observedC,actual_steps=actualSteps,decisions};
    }
    private string[] OptionNames(CombatHotState s,StepEvent ev){
        return ev.Choices.Select(o=>{
            if(o.Kind==HotChoiceKind.GeneratedCard)return rules.Cards[o.Def].Entry+"#0";
            if(o.Kind==HotChoiceKind.None)return "skip";
            int pos=HotCombatEngine.FindCardIndexByUidAnyPile(in s,o.Instance);
            if(pos<0)throw new NotSupportedException("prompt/unbound_instance");
            return Token(s.Cards[pos]);
        }).ToArray();
    }
    public object Play(int index)
    {
        if(decisions>=128)throw new NotSupportedException("decision_cap");
        decisions++;
        if(prompt!=null){
            if((uint)index>=prompt.Choices.Length)throw new ArgumentOutOfRangeException(nameof(index));
            transcript=transcript.AddChoice(prompt,prompt.Choices[index]);prompt=null;
        }else{
            if((uint)index>=menu.Length)throw new ArgumentOutOfRangeException(nameof(index));
            waiting=menu[index];transcript=Prefix.Empty;
        }
        var child=world;var side=cold;var scratch=new HotExecScratch();
        // The kernel restarts an interrupted action from its parent on selection.
        // Undo only descriptor writes from the temporary prefix before replay.
        var prior=new Dictionary<ushort,(bool Known,HotCard Card,(ushort Def,byte Up)? Label)>();
        void PublishStep(HotCard c){
            if(!prior.ContainsKey(c.CardUid)){
                bool known=declaredCards.TryGetValue(c.CardUid,out var old);
                prior.Add(c.CardUid,(known,old,labels.TryGetValue(c.CardUid,out var label)?label:null));
            }
            Publish(c);
        }
        bool committed=false;
        var probe=new Probe(rules,law,transcript,waiting.Kind.ToString(),Resolution.CaptureWorld);
        observedC=null;
        try{
            Probe.Current=probe;
            Probe.Published=PublishStep;
            Probe.Declared=id=>declaredCards[id];
            InfraCObserver.BeforeDraw=(in CombatHotState s,HotColdSidecar? c,HotRules r,int draw)=>
                observedC=new{facts=Facts(s,c,probe.Belief,[]),draw};
            actualSteps++;
            var result=HotCombatEngine.Step(ref child,ref side,rules,scratch,waiting);
            probe.RequireConsumed();
            if(result.NeedsChoice || !result.Executed)throw new NotSupportedException("actual/unhandled_input");

            probe.Belief.Validate(in child,true);
            world=child;cold=side;law=probe.Belief;Remember();committed=true;
        }catch(Boundary b) when(b.Status==StepStatus.NeedsChoice){
            prompt=probe.Events[^1];
            var options=OptionNames(child,prompt);
            var facts=Facts(child,side,probe.Belief,[]);
            return new{status="choice",kind=prompt.Phase,options,facts,view=Stamp(facts,new{kind=prompt.Phase,options}),actual_steps=actualSteps,decisions};
        }catch(Boundary b){throw new NotSupportedException(b.Point+"/"+b.Message);}
        finally{
            if(!committed)foreach(var (id,entry) in prior){
                if(entry.Known)declaredCards[id]=entry.Card;else declaredCards.Remove(id);
                if(entry.Label is {} l)labels[id]=l;else labels.Remove(id);
            }
            Probe.Declared=null;Probe.Published=null;Probe.Current=null;InfraCObserver.BeforeDraw=null;HotCombatEngine.ClearPendingChoiceUidFilters();}
        return View();
    }
}
