using System.Text.Json;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;
using MegaCrit.Sts2.Core.Combat;

public static partial class PublicBranch
{
    private static bool slugMode;
    private static object[] SlugRoster(in CombatHotState state)
    {
        var result=new List<object>();
        for(int i=0;i<state.EnemyCount;i++){
            var e=state.Enemies[i];
            var move=rules.GetMonsterMachine(e.MonsterDefId)!.Nodes[e.CurrentMoveNode];
            result.Add(new{slot=i,alive=(e.Vital.Flags&HotCreatureFlags.Alive)!=0,hp=e.Vital.CurrentHp,
                max_hp=e.Vital.MaxHp,block=e.Vital.Block,move=move.MoveId,
                attack_hits=move.Attacks.SelectMany(a=>Enumerable.Repeat((int)a.BaseDamage,a.Repeats)).ToArray()});
        }
        return result.ToArray();
    }

    // A pre-draw C and the observed opening hand from that same round are public.
    // Never import the hidden physical order or live combat counters.
    private static void OpenSlugs(JsonElement cmd)
    {
        ClearNodes();slugMode=true;
        var h=cmd.GetProperty("wire");var c=cmd.GetProperty("prior");
        var law=cmd.GetProperty("law");
        if(Integer(h,"turn")!=2 || Integer(c,"turn")!=2 || Integer(cmd,"ascension")!=0 ||
           Integer(h.GetProperty("mechanism"),"played")!=0 || h.GetProperty("decision").GetProperty("phase").GetString()!="combat" ||
           c.GetProperty("enemies").GetArrayLength()!=3 || c.GetProperty("relics").GetArrayLength()!=0 ||
           c.GetProperty("potions").EnumerateArray().Any(p=>p.ValueKind!=JsonValueKind.Null) ||
           Integer(law,"shuffles")!=0 || law.GetProperty("top").GetArrayLength()+law.GetProperty("bottom").GetArrayLength()!=0)
            throw new Stop("slugs/root_scope");
        foreach(var k in new[]{"membership_gap","order_gap"})
            if(law.TryGetProperty(k,out var val) && val.ValueKind!=JsonValueKind.Null)throw new Stop("slugs/pile_gap");
        rules=HotRootBuilder.BuildFromLive(CombatManager.Instance.DebugOnlyGetState()!).Rules;
        var s=new CombatHotState{CombatFlags=HotCombatFlags.IsInProgress|HotCombatFlags.PlayerHooksActive,
            CurrentSide=HotCombatSide.Player,PlayerTurnNumber=2,RoundNumber=2,MaxHandSize=10,
            PlayerPhase=1,NextCardUid=1,NextCreatureId=4,Gold=Integer(c,"gold"),PotionSlotCount=3,
            Energy=Integer(h,"energy"),Stars=Integer(h,"stars"),EnemyCount=3,RosterCount=3};
        s.Player=new(){CombatId=0,SlotIdx=0,Flags=HotCreatureFlags.Alive|HotCreatureFlags.ActiveInRoster|HotCreatureFlags.IsPlayer,
            CurrentHp=Integer(h,"hp"),MaxHp=Integer(h,"max_hp"),Block=Integer(h,"block")};
        void Powers(JsonElement source,byte owner){
            foreach(var p in source.EnumerateArray()){
                string id=p.GetProperty("id").GetString()!;
                if((owner==0 && id!="FRAIL_POWER") || (owner!=0 && id!="RAVENOUS_POWER"))throw new Stop("slugs/power/"+id);
                s.Powers[s.PowerCount++]=new(){OwnerSlot=owner,ApplierSlot=255,TargetSlot=255,Amount=Integer(p,"amount"),
                    AmountOnTurnStart=Integer(p,"amount"),PowerDefId=rules.PowerDefIdByEntry[id]};
            }
        }
        Powers(c.GetProperty("powers"),0);
        var def=rules.MonsterDefIdByEntry["CORPSE_SLUG"];
        var machine=rules.GetMonsterMachine(def)!;
        for(int i=0;i<3;i++){
            var foe=c.GetProperty("enemies")[i];var visible=h.GetProperty("enemies")[i];
            var phase=foe.GetProperty("phase");
            if(foe.GetProperty("species").GetString()!="CORPSE_SLUG" || phase.GetProperty("registers").EnumerateObject().Any() ||
                phase.GetProperty("repeat_windows").EnumerateObject().Any())throw new Stop("slugs/history");
            var enemy=new HotEnemy{MonsterDefId=def,CurrentMoveNode=machine.FindNode(foe.GetProperty("move").GetString()!),
                Vital=new(){CombatId=(uint)(i+1),SlotIdx=(byte)(3+i),Flags=HotCreatureFlags.Alive|HotCreatureFlags.ActiveInRoster,
                    CurrentHp=Integer(visible,"hp"),MaxHp=Integer(foe,"max_hp"),Block=Integer(visible,"block")}};
            foreach(var past in phase.GetProperty("committed_moves").EnumerateArray()){
                short node=machine.FindNode(past.GetString()!);
                if(node<0 || node>=64 || enemy.RecentMoveCount>=8)throw new Stop("slugs/move_history");
                enemy.RecentMoves[enemy.RecentMoveCount++]=(byte)node;enemy.EverUsedMovesMask|=1UL<<node;
            }
            s.Enemies[i]=enemy;s.ActiveEnemyRoster[i]=(byte)i;
            Powers(foe.GetProperty("powers"),(byte)(3+i));
        }
        var ids=new List<ushort>();
        void Add(string id,int up,HotPileKind pile,int? cost){
            var definition=rules.Cards[rules.CardDefIdByEntry[id]];
            var card=HotCombatEngine.CreateFreshCard(ref s,definition,up!=0);
            if(cost.HasValue && cost!=(EnergyX(card)?s.Energy:card.BaseEnergyCost))throw new Stop("slugs/instance_cost/"+id);
            card.Flags|=HotCardFlags.HasDeckVersion;s.Cards[s.TotalCardCount]=card;
            switch(pile){
                case HotPileKind.Hand:s.HandCount++;break;
                case HotPileKind.Draw:s.DrawCount++;ids.Add(card.CardUid);break;
                case HotPileKind.Discard:s.DiscardCount++;break;
                case HotPileKind.Exhaust:s.ExhaustCount++;break;
            }
        }
        void Visible(string zone,HotPileKind pile){
            foreach(var card in h.GetProperty(zone).EnumerateArray()){
                if(card.TryGetProperty("enchantment",out _) || card.TryGetProperty("affliction",out _))throw new Stop("slugs/modifier");
                Add(card.GetProperty("id").GetString()!,Integer(card,"upgrade"),pile,card.TryGetProperty("cost",out var v)?v.GetInt32():null);
            }
        }
        foreach(var zone in c.GetProperty("card_state").EnumerateObject())
            foreach(var card in zone.Value.EnumerateArray())
                if(card.GetProperty("cost_layers").EnumerateObject().Any(p=>p.Value.GetArrayLength()!=0))throw new Stop("slugs/cost_layers");
        Visible("hand",HotPileKind.Hand);
        foreach(var item in law.GetProperty("counts").EnumerateObject().OrderBy(k=>k.Name,StringComparer.Ordinal)){
            var parts=item.Name.Split('#');
            for(int j=0;j<item.Value.GetInt32();j++)Add(parts[0],int.Parse(parts[1]),HotPileKind.Draw,null);
        }
        Visible("discard",HotPileKind.Discard);Visible("exhaust",HotPileKind.Exhaust);
        if(ids.Count!=Integer(h,"draw_count"))throw new Stop("slugs/draw_count");
        s.ActiveHookMask=HotCombatEngine.RecomputeActiveHookMask(in s,rules);
        Save(new Snapshot(in s,null,DrawBelief.Create([],ids,[])));
    }
}
