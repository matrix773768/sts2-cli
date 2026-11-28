using System.Text.Json;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;
using MegaCrit.Sts2.Core.Combat;

// Only static definitions cross the live-engine boundary. Parents are never mutated.
public static partial class PublicBranch
{
    private sealed class Stop(string reason) : Exception(reason);
    private sealed class AtC : Exception;
    private static readonly Dictionary<int, Snapshot> nodes = new();
    private static HotRules rules = null!;
    private static int sequence;
    private static long steps, replays, saved, reused;
    private static readonly Dictionary<int,Dictionary<(int Slot,int Target,string Key),Prefix>> inputsByParent=new();
    private static void ClearNodes(){nodes.Clear();inputsByParent.Clear();}
    private static void ResetMetrics(){steps=0;replays=0;saved=0;reused=0;}
    private static readonly HashSet<string> variables = new() {
        "Damage","Block","Cards","Energy","HitCount","Repeat","StrengthPower","DexterityPower","VulnerablePower"
    };
    private static int Integer(JsonElement row,string key) => row.GetProperty(key).GetInt32();
    private static bool EnergyX(HotCard card) => (card.Flags&HotCardFlags.CostsX)!=0;
    private static string Name(HotCard card) => rules.Cards[card.CardDefId].Entry;
    private static string Token(HotCard card) => Name(card)+"#"+card.UpgradeLevel;
    private static int Save(Snapshot node) { int id=checked(++sequence); nodes.Add(id,node); saved++; return id; }
    private static void Open(JsonElement cmd)
    {
        ClearNodes();
        slugMode=false;
        var h=cmd.GetProperty("wire");
        var mech=h.GetProperty("mechanism");
        if(Integer(h,"turn")!=1 || Integer(mech,"played")!=0 ||
           mech.GetProperty("species").GetArrayLength()!=1 || mech.GetProperty("species")[0].GetString()!="MECHA_KNIGHT")
            throw new Stop("opening/encounter_or_history");
        if(h.GetProperty("relics").GetArrayLength()!=0 || h.GetProperty("potions").EnumerateArray().Any(p=>p.ValueKind!=JsonValueKind.Null))
            throw new Stop("opening/persistent_hooks");
        var hooks=h.GetProperty("order_hooks").EnumerateArray().ToArray();
        if(hooks.Length!=1 || hooks[0].GetProperty("id").GetString()!="ARTIFACT_POWER" || Integer(hooks[0],"owner")!=0)
            throw new Stop("opening/power");
        // This ascension-zero encounter always opens in CHARGE_MOVE. Only its static
        // definitions are retained from the native initialization.
        if(Integer(cmd,"ascension")!=0)throw new Stop("opening/ascension");
        rules=HotRootBuilder.BuildFromLive(CombatManager.Instance.DebugOnlyGetState()!).Rules;
        var enemy=h.GetProperty("enemies")[0];
        var species=rules.MonsterDefIdByEntry["MECHA_KNIGHT"];
        var machine=rules.GetMonsterMachine(species)!;
        short move=machine.FindNode("CHARGE_MOVE");
        var s=new CombatHotState { CombatFlags=HotCombatFlags.IsInProgress|HotCombatFlags.PlayerHooksActive,
            CurrentSide=HotCombatSide.Player, PlayerTurnNumber=1, RoundNumber=1, MaxHandSize=10,
            PlayerPhase=1, NextCardUid=cmd.TryGetProperty("audit_uid_base",out var uidBase)?uidBase.GetUInt16():(ushort)1, NextCreatureId=2, Gold=Integer(cmd,"gold"), PotionSlotCount=3,
            Energy=Integer(h,"energy"), Stars=Integer(h,"stars"), EnemyCount=1,RosterCount=1 };
        s.Player=new(){CombatId=0,SlotIdx=0,Flags=HotCreatureFlags.Alive|HotCreatureFlags.ActiveInRoster|HotCreatureFlags.IsPlayer,CurrentHp=Integer(h,"hp"),
            MaxHp=Integer(h,"max_hp"),Block=Integer(h,"block")};
        s.Enemies[0]=new(){MonsterDefId=species, CurrentMoveNode=move,RecentMoveCount=1,
            Vital=new(){CombatId=1,SlotIdx=3,Flags=HotCreatureFlags.Alive|HotCreatureFlags.ActiveInRoster,CurrentHp=Integer(enemy,"hp"),
                MaxHp=Integer(enemy,"hp"),Block=Integer(enemy,"block")}};
        s.Enemies[0].RecentMoves[0]=checked((byte)move);
        s.Enemies[0].EverUsedMovesMask=1UL<<move;
        var power=mech.GetProperty("stacks")[0];
        s.Powers[0]=new(){PowerDefId=rules.PowerDefIdByEntry["ARTIFACT_POWER"],OwnerSlot=3,
            ApplierSlot=255,TargetSlot=255,Amount=Integer(power,"amount"),AmountOnTurnStart=Integer(power,"amount")};
        s.PowerCount=1;
        var unknown=new List<ushort>();
        void Add(string id,int up,HotPileKind pile,int? cost)
        {
            if(up is <0 or >1 || !rules.CardDefIdByEntry.TryGetValue(id,out ushort def) || s.TotalCardCount>=HotLimits.MaxCards)
                throw new Stop("opening/card");
            var card=HotCombatEngine.CreateFreshCard(ref s,rules.Cards[def],up!=0);
            if(cost.HasValue && cost.Value!=(EnergyX(card)?s.Energy:card.BaseEnergyCost))throw new Stop("opening/changed_cost");
            card.Flags|=HotCardFlags.HasDeckVersion;
            s.Cards[s.TotalCardCount]=card;
            if(pile==HotPileKind.Hand)s.HandCount++;
            else {s.DrawCount++;unknown.Add(card.CardUid);}
        }
        foreach(var card in h.GetProperty("deck").EnumerateArray())
            if(card.TryGetProperty("affliction",out _) || card.TryGetProperty("enchantment",out _))throw new Stop("opening/modifier");
        foreach(var card in h.GetProperty("hand").EnumerateArray())
            Add(card.GetProperty("id").GetString()!,Integer(card,"upgrade"),HotPileKind.Hand,Integer(card,"cost"));
        foreach(var prop in cmd.GetProperty("counts").EnumerateObject().OrderBy(p=>p.Name,StringComparer.Ordinal)){
            var pair=prop.Name.Split('#');
            for(int i=0;i<prop.Value.GetInt32();i++)Add(pair[0],int.Parse(pair[1]),HotPileKind.Draw,null);
        }
        if(h.GetProperty("discard").GetArrayLength()!=0 || h.GetProperty("exhaust").GetArrayLength()!=0 ||
            unknown.Count!=Integer(h,"draw_count"))throw new Stop("opening/pile_law");
        s.ActiveHookMask=HotCombatEngine.RecomputeActiveHookMask(in s,rules);
        Save(new Snapshot(in s,null,DrawBelief.Create([],unknown,[])));
    }

    private static object Facts(Snapshot parent)
    {
        var s=parent.State;
        object Card(HotCard c){
            var d=rules.Cards[c.CardDefId];
            if(c.CostModCount!=0 || c.EnchId!=0 || c.AfflId!=0 || c.Var0Delta!=0 || c.Var1Delta!=0)
                throw new Stop("export/modified_instance");
            var values=c.UpgradeLevel==0?d.BaseVarValues:d.UpgradedVarValues;
            return new{id=d.Entry,upgrade=(int)c.UpgradeLevel,energy_x=EnergyX(c),cost=EnergyX(c)?s.Energy:(int)c.BaseEnergyCost, uid=c.CardUid,
                vars=d.OrderedVarNames.Select((name,i)=>(name,i)).Where(x=>variables.Contains(x.name))
                    .ToDictionary(x=>x.name,x=>values[x.i])};
        }
        object[] Zone(HotPileKind pile) => Enumerable.Range(HotPiles.ZoneStart(in s,pile),HotPiles.ZoneCount(in s,pile))
            .Select(i=>Card(s.Cards[i])).ToArray();
        var powers=Enumerable.Range(0,s.PowerCount).Select(i=>new {id=rules.Powers[s.Powers[i].PowerDefId].Entry,
            owner=(int)s.Powers[i].OwnerSlot,amount=s.Powers[i].Amount}).ToArray();
        var e=s.Enemies[0];var m=rules.GetMonsterMachine(e.MonsterDefId)!.Nodes[e.CurrentMoveNode];
        var actions=new List<object>();
        for(int j=0;j<s.HandCount;j++){
            if(!HotCombatEngine.CanPlayCard(in s,parent.Cold,rules,j))continue;
            var c=s.Cards[j]; var d=rules.Cards[c.CardDefId];
            actions.Add(new{slot=j,target=d.Target.ToString(),category=d.Type.ToString(),damage=d.GetDamage(c.UpgradeLevel,0),
                hits=d.GetHits(c.UpgradeLevel),block=d.GetBlock(c.UpgradeLevel,0),stars=(int)c.BaseStarCost});
        }
        var labels=new Dictionary<ushort,string>();
        for(int i=s.DrawStart;i<s.DiscardStart;i++)labels.Add(s.Cards[i].CardUid,Token(s.Cards[i]));
        return new {turn=s.PlayerTurnNumber,round=s.RoundNumber,hp=s.Player.CurrentHp,max_hp=s.Player.MaxHp,block=s.Player.Block,
            energy=s.Energy,stars=s.Stars,gold=s.Gold,draw_count=s.DrawCount,
            played=s.Counters[(int)HotCounterSlot.CardPlayStartsThisTurn],attacks=s.Counters[(int)HotCounterSlot.AttackPlayStartsThisTurn],
            skills=s.Counters[(int)HotCounterSlot.SkillPlayStartsThisTurn],powers,actions,hand=Zone(HotPileKind.Hand),
            discard=Zone(HotPileKind.Discard),exhaust=Zone(HotPileKind.Exhaust),move=m.MoveId,
            attack_hits=m.Attacks.SelectMany(a=>Enumerable.Repeat((int)a.BaseDamage,a.Repeats)).ToArray(),
            foes=slugMode?SlugRoster(in s):null,enemy_hp=e.Vital.CurrentHp,enemy_max_hp=e.Vital.MaxHp,enemy_block=e.Vital.Block,
            top=parent.Belief.Top.Select(id=>labels[id]).ToArray(),bottom=parent.Belief.Bottom.Select(id=>labels[id]).ToArray(),
            counts=parent.Belief.OrderedIds().GroupBy(id=>labels[id]).ToDictionary(g=>g.Key,g=>g.Count()),shuffles=parent.Belief.Generation};
    }
    private static object Advance(JsonElement cmd)
    {
        int parentId=Integer(cmd,"parent");
        Snapshot parent=nodes[parentId];
        var s=parent.State; var cold=parent.Cold;
        int slot=Integer(cmd,"slot");
        int target=Integer(cmd,"target");
        var action=slot<0?HotAction.EndTurn():HotAction.PlayCard(slot,target);
        if(slot>=0 && (!HotCombatEngine.CanPlayCard(in s,cold,rules,slot) ||
           Name(s.Cards[slot]) is not ("STRIKE_IRONCLAD" or "DEFEND_IRONCLAD" or "SHRUG_IT_OFF" or "POMMEL_STRIKE" or "TWIN_STRIKE" or "IRON_WAVE" or "HEMOKINESIS" or "BURNING_PACT" or "HEADBUTT" or "FORGOTTEN_RITUAL" or "BASH" or "BLOOD_WALL" or "BLOODLETTING" or "FIEND_FIRE" or "BATTLE_TRANCE" or "DEMON_FORM" or "THRASH" or "EVIL_EYE" or "PRIMAL_FORCE" or "STOKE" or "DISMANTLE" or "DARK_EMBRACE" or "JUGGLING" or "CRIMSON_MANTLE" or "PILLAGE" or "RAMPAGE" or "ARMAMENTS" or "BODY_SLAM")))
            throw new Stop("action/"+Name(s.Cards[slot]));
        var prefix=Prefix.Empty;
        var inputs=cmd.GetProperty("inputs").EnumerateArray().ToArray();
        if(!inputsByParent.TryGetValue(parentId,out var known))inputsByParent.Add(parentId,known=new());
        // These are public event addresses and validated selections, never paused
        // mutable states. A sibling still executes its action from the stable value.
        static string Append(string key,string value)=>key+value.Length+":"+value;
        var keys=new string[inputs.Length+1];keys[0]="";
        for(int j=0;j<inputs.Length;j++){
            var input=inputs[j];
            string token=input.ValueKind==JsonValueKind.String?"d"+input.GetString():"c"+input.GetUInt16();
            keys[j+1]=Append(keys[j],token);
        }
        int start=inputs.Length;
        while(start>0 && !known.TryGetValue((slot,target,keys[start]),out prefix!))start--;
        if(start==0)prefix=Prefix.Empty;
        else reused+=start;
        for(int i=start;;i++){
            s=parent.State;cold=parent.Cold;
            var probe=new Probe(rules,parent.Belief,prefix,slot<0?"end_turn":Name(s.Cards[slot]),Resolution.Public);
            if(Probe.Current!=null || InfraCObserver.BeforeDraw!=null)throw new InvalidOperationException("Nested Hot transition");
            Probe.Current=probe;object? captured=null;
            InfraCObserver.BeforeDraw=(in CombatHotState at,HotColdSidecar? side,HotRules r,int draw)=>{
                var snap=new Snapshot(in at,side,probe.Belief);
                captured=new{kind="C",facts=Facts(snap),draw};throw new AtC();
            };
            try{
                steps++; if(i>start)replays++;
                var result=HotCombatEngine.Step(ref s,ref cold,rules,new HotExecScratch(),action);
                probe.RequireConsumed();
                if(!result.Executed || result.NeedsChoice || i!=inputs.Length)throw new Stop("action/unhandled_boundary");
                if(s.TerminalOutcome!=HotCombatOutcome.Ongoing)return new{kind=s.TerminalOutcome==HotCombatOutcome.Victory?"victory":"death",
                    state=new{hp=s.Player.CurrentHp,max_hp=s.Player.MaxHp},gold=s.Gold};
                var child=new Snapshot(in s,cold,probe.Belief);
                child.Belief.Validate(in s,true);
                var facts=Facts(child);
                return new{kind="decision",node=Save(child),facts};
            }catch(AtC){probe.RequireConsumed();if(i!=inputs.Length)throw new Stop("trailing_input");return captured!;}
            catch(Boundary b) when(b.Status==StepStatus.NeedsChance || b.Status==StepStatus.NeedsChoice){
                var ev=probe.Events[^1];
                if(ev.Kind==EventKind.PlayerChoice){
                    foreach(var option in ev.Choices)
                        known.TryAdd((slot,target,Append(keys[i],"c"+option.Instance)),prefix.AddChoice(ev,option));
                    if(i==inputs.Length)return new{kind="choice",facts=Facts(new Snapshot(in s,cold,probe.Belief)),options=ev.Choices.Select(x=>new{kind=x.Kind.ToString(),uid=x.Instance})};
                    prefix=prefix.AddChoice(ev,ev.Choices.Single(x=>x.Instance==inputs[i].GetUInt16()));continue;
                }
                string Label(ushort uid){
                    for(int j=0;j<s.TotalCardCount;j++)if(s.Cards[j].CardUid==uid)return Token(s.Cards[j]);
                    throw new Stop("draw/lost_instance");
                }
                var groups=ev.Options.GroupBy(x=>Label(x.Instance)).ToDictionary(g=>g.Key,g=>g.ToArray());
                foreach(var (label,options) in groups)
                    if(options.All(o=>o.Observation==options[0].Observation))
                        known.TryAdd((slot,target,Append(keys[i],"d"+label)),prefix.AddDraw(ev,options[0].Instance));
                if(i==inputs.Length)return new{kind="R",support=groups.ToDictionary(p=>p.Key,p=>p.Value.Length),batch=ev.Remaining};
                var opts=groups[inputs[i].GetString()!];
                if(opts.Select(x=>x.Observation).Distinct().Count()!=1)throw new Stop("draw/nonexchangeable_copies");
                prefix=prefix.AddDraw(ev,opts[0].Instance);
            }finally{Probe.Current=null;InfraCObserver.BeforeDraw=null;HotCombatEngine.ClearPendingChoiceUidFilters();}
        }
    }
    public static object Request(JsonElement cmd){
        try{
            switch(cmd.GetProperty("op").GetString()){
                case "identity":return AppDomain.CurrentDomain.GetAssemblies().Where(a=>!a.IsDynamic &&
                    (a.GetName().Name=="sts2" || a.GetName().Name!.StartsWith("STS2-RitsuLib",StringComparison.Ordinal)))
                    .Select(a=>new{name=a.GetName().Name,path=a.Location,sha256=Convert.ToHexStringLower(
                        System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(a.Location)))}).ToArray();
                case "stats":return new{steps,replays,saved,reused,transcripts=inputsByParent.Values.Sum(t=>t.Count),live=nodes.Count,value_bytes=System.Runtime.CompilerServices.Unsafe.SizeOf<CombatHotState>()};
                case "open_slugs":ResetMetrics();OpenSlugs(cmd);return new{kind="decision",node=sequence,facts=Facts(nodes[sequence])};
                case "open":ResetMetrics();Open(cmd);return new{kind="decision",node=sequence,facts=Facts(nodes[sequence])};
                case "advance":return Advance(cmd);
                case "release":int id=Integer(cmd,"node");inputsByParent.Remove(id);return new{released=nodes.Remove(id)};
                case "clear":ClearNodes();return new{kind="cleared"};
                default:throw new Stop("unknown_operation");
            }
        }catch(Exception e) when(e is Stop or Boundary or HotCapacityExceededException or KeyNotFoundException or InvalidOperationException){
            return new{kind="unsupported",reason=e.Message};
        }
    }
}
