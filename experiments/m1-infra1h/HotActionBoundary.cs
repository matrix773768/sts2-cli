using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using CombatSolver.HotKernel;
using CombatSolver.HotDraw;

// Partial public import for one contract: the next unresolved card draw within
// a self-targeting card play. No post-action state is published by this operator.
public static class HotActionBoundary
{
    private static CombatState? native;
    private static HotRules? rules;
    public static int Next(JsonElement h,Dictionary<string,int> counts,int handSlot,int maxHand)
    {
        var live=CombatManager.Instance.DebugOnlyGetState();
        if(live==null)return -1;
        if(!ReferenceEquals(live,native))
        {
            native=live;rules=null;
            // Retain static card definitions and encounter rules only. Neither the
            // imported hot value, private RNG nor cold data enters this search.
            rules=HotRootBuilder.BuildFromLive(live).Rules;
        }
        if(rules==null)return -1;
        var rule=rules;
        var hand=h.GetProperty("hand");
        var selected=hand[handSlot].GetProperty("id").GetString()!;
        if(selected is not ("BATTLE_TRANCE" or "SHRUG_IT_OFF" or "OFFERING"))return -1;
        if(rule.ActiveRelicDefIds.Any(i=>rule.Relics[i].Entry!="BURNING_BLOOD") ||
            rule.RootPets.Length!=0 || rule.Dominion!=HotDominionId.None)return -1;
        var s=new CombatHotState{CombatFlags=HotCombatFlags.IsInProgress|HotCombatFlags.PlayerHooksActive,
            CurrentSide=HotCombatSide.Player,NextCardUid=1,MaxHandSize=checked((byte)maxHand),
            PlayerTurnNumber=h.GetProperty("turn").GetInt32(),Energy=h.GetProperty("energy").GetInt32(),
            Stars=h.GetProperty("stars").GetInt32()};
        s.Player=new(){CurrentHp=h.GetProperty("hp").GetInt32(),MaxHp=h.GetProperty("max_hp").GetInt32(),
            Block=h.GetProperty("block").GetInt32(),CombatId=1,Flags=HotCreatureFlags.Alive};
        if(selected=="OFFERING" && s.Player.CurrentHp<=12)return -1;
        var species=h.GetProperty("mechanism").GetProperty("species");
        var enemies=h.GetProperty("enemies");
        if(enemies.GetArrayLength()>HotLimits.MaxEnemies)return -1;
        for(int i=0;i<enemies.GetArrayLength();i++)
        {
            if(!rule.MonsterDefIdByEntry.TryGetValue(species[i].GetString()!,out var def))return -1;
            int hp=enemies[i].GetProperty("hp").GetInt32();
            s.Enemies[i]=new(){MonsterDefId=def,Vital=new(){CombatId=(uint)(2+i),Flags=HotCreatureFlags.Alive,
                SlotIdx=(byte)(3+i),CurrentHp=hp,MaxHp=hp,Block=enemies[i].GetProperty("block").GetInt32()}};
            s.ActiveEnemyRoster[i]=(byte)i;s.RosterCount++;s.EnemyCount++;
        }
        var ids=new List<ushort>();
        bool Add(ref CombatHotState state,string id,int up,HotPileKind zone,int? cost)
        {
            if(up is <0 or >1 || state.TotalCardCount>=HotLimits.MaxCards ||
                !rule.CardDefIdByEntry.TryGetValue(id,out var def))return false;
            var c=HotCombatEngine.CreateFreshCard(ref state,rule.Cards[def],up==1);
            if(cost.HasValue && c.BaseEnergyCost!=cost.Value)return false;
            state.Cards[state.TotalCardCount]=c;
            switch(zone){case HotPileKind.Hand:state.HandCount++;break;
                case HotPileKind.Draw:state.DrawCount++;ids.Add(c.CardUid);break;
                case HotPileKind.Discard:state.DiscardCount++;break;
                case HotPileKind.Exhaust:state.ExhaustCount++;break;}
            return true;
        }
        bool AddVisible(ref CombatHotState state,JsonElement zone,HotPileKind k)
        {
            foreach(var card in zone.EnumerateArray())
            {
                if(card.TryGetProperty("affliction",out _) || card.TryGetProperty("enchantment",out _))return false;
                int? cost=card.TryGetProperty("cost",out var cc)?cc.GetInt32():null;
                if(!Add(ref state,card.GetProperty("id").GetString()!,card.GetProperty("upgrade").GetInt32(),k,cost))return false;
            }
            return true;
        }
        if(!AddVisible(ref s,hand,HotPileKind.Hand))return -1;
        foreach(var kv in counts.OrderBy(x=>x.Key,StringComparer.Ordinal))
        {
            var parts=kv.Key.Split('#');
            if(parts.Length!=2 || !int.TryParse(parts[1],out int up))return -1;
            for(int n=0;n<kv.Value;n++)if(!Add(ref s,parts[0],up,HotPileKind.Draw,null))return -1;
        }
        if(!AddVisible(ref s,h.GetProperty("discard"),HotPileKind.Discard) ||
           !AddVisible(ref s,h.GetProperty("exhaust"),HotPileKind.Exhaust))return -1;
        s.ActiveHookMask=HotCombatEngine.RecomputeActiveHookMask(in s,rule);
        if(!HotCombatEngine.CanPlayCard(in s,null,rule,handSlot))return -1;
        var probe=new Probe(rule,DrawBelief.Create([],ids,[]),Prefix.Empty,selected,Resolution.Public);
        HotColdSidecar? cold=null;
        if(Probe.Current!=null)throw new InvalidOperationException("Nested HotKernel search");
        Probe.Current=probe;
        try{HotCombatEngine.Step(ref s,ref cold,rule,new HotExecScratch(),HotAction.PlayCard(handSlot));}
        catch(Boundary b) when(b.Status==StepStatus.NeedsChance)
        {
            var e=probe.Events[^1];
            if(e.Kind!=EventKind.Draw || e.Options.Length!=ids.Count)return -1;
            return Math.Min(Math.Min(e.Remaining,s.DrawCount),maxHand-s.HandCount);
        }
        catch(Boundary){return -1;}
        finally{Probe.Current=null;HotCombatEngine.ClearPendingChoiceUidFilters();}
        return -1;
    }
}
