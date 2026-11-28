using CombatSolver.HotKernel;
using MegaCrit.Sts2.Core.MonsterMoves;
using CombatSolver.HotDraw;

internal sealed partial class Battle
{
    private object Facts(CombatHotState s,HotColdSidecar? side,DrawBelief belief,HotAction[] actions,bool hypothetical=false)
    {
        var byId=new Dictionary<ushort,string>();
        if(hypothetical)
            foreach(var c in Zone(s,HotPileKind.Draw))byId.Add(c.CardUid,Token(c));
        string Name(ushort id)=>hypothetical?byId[id]:Label(id);
        var counts=new Dictionary<string,int>(belief.Counts??throw new InvalidOperationException("public counts missing"));
        if(counts.Values.Sum()!=s.DrawCount)throw new InvalidOperationException("public draw count mismatch");
        object Card(HotCard c,int index){
            var d=rules.Cards[c.CardDefId];
            var values=c.UpgradeLevel==0?d.BaseVarValues:d.UpgradedVarValues;
            var vars=d.OrderedVarNames.Select((n,i)=>(n,i)).Where(x=>x.n is "Damage" or "Block" or "Cards" or "Energy" or "HitCount" or "Repeat" or "StrengthPower" or "DexterityPower" or "VulnerablePower").ToDictionary(x=>x.n,x=>values[x.i]+(x.i==d.Var0Index?c.Var0Delta:x.i==d.Var1Index?c.Var1Delta:0));
            bool energyX=(c.Flags&HotCardFlags.CostsX)!=0;
            return new{index,id=d.Entry,upgrade=(int)c.UpgradeLevel,cost=Math.Max(0,HotCombatEngine.GetEffectiveEnergyCost(in s,in c,side,rules,true)),
                star_cost=(int)c.BaseStarCost,energy_x=energyX,target_type=HotCombatEngine.GetEffectiveCardTargetType(in s,in c,d,rules).ToString(),
                damage=d.GetDamage(c.UpgradeLevel,c.Var0Delta),hits=d.GetHits(c.UpgradeLevel),block=d.GetBlock(c.UpgradeLevel,c.Var1Delta),
                vars,cost_layers=new{energy=Enumerable.Range(0,HotCostModifiers.GetEnergyModifierCount(in c,side)).Select(i=>HotCostModifiers.GetEnergyModifierAt(in c,side,i)).Select(m=>new{amount=m.Amount,kind=m.IsAbsolute?"Absolute":"Relative",expires=m.ExpirationEnum.ToString(),reduce_only=m.IsReduceOnly}).ToArray(),
                    stars=Enumerable.Range(0,HotCostModifiers.GetTempStarCostCount(in c,side)).Select(i=>HotCostModifiers.GetTempStarCostAt(in c,side,i)).Select(m=>new{cost=m.Cost,clears_when_turn_ends=m.ClearsWhenTurnEnds,clears_when_card_is_played=m.ClearsWhenCardIsPlayed}).ToArray()},cost_mods=c.CostModCount,enchantment=c.EnchId==0?null:rules.Enchantments[c.EnchId].Entry,
                affliction=c.AfflId==0?null:rules.Afflictions[c.AfflId].Entry,enchantment_amount=c.EnchAmt,affliction_amount=c.AfflAmt};
        }
        object[] Cards(HotPileKind pile)=>Zone(s,pile).Select(Card).ToArray();
        object[] Powers(int slot)=>Enumerable.Range(0,s.PowerCount).Select(i=>s.Powers[i]).Where(p=>p.OwnerSlot==slot && VisiblePower(p.PowerDefId)).OrderBy(p=>rules.Powers[p.PowerDefId].Entry,StringComparer.Ordinal)
            .Select(p=>(object)new{id=rules.Powers[p.PowerDefId].Entry,amount=p.Amount}).ToArray();
        var enemies=new List<object>();var strategicEnemies=new Dictionary<int,object>(); var slots=new Dictionary<int,int>();
        for(int j=0;j<s.RosterCount;j++){
            int slot=s.ActiveEnemyRoster[j]; var e=s.Enemies[slot];
            if((e.Vital.Flags&HotCreatureFlags.Alive)==0)continue;
            var machine=rules.GetMonsterMachine(e.MonsterDefId)??throw new NotSupportedException("enemy/missing_machine");
            var m=machine.Nodes[e.CurrentMoveNode];
            var history=announced.GetValueOrDefault(e.Vital.CombatId)??[];
            var moves=history.Select(i=>machine.Nodes[i].MoveId).ToList();
            if(s.PlayerTurnNumber!=recordedTurn)moves.Add(m.MoveId);
            slots.Add(slot,enemies.Count);
            var monster=rules.Monsters[e.MonsterDefId];
            var hits=new List<int>();
            void Hit(int damage,int repeats){
                var sample=s;var sampleSide=side;
                int basis=HotMonsters.AdjustMonsterMoveDamage(in s,(byte)slot,monster.MonsterId,m.MoveId,damage);
                int amount=(int)HotCombatEngine.ComputeModifiedDamage(ref sample,ref sampleSide,rules,new HotExecScratch(),(byte)(slot+3),0,basis,true,-1,0);
                hits.AddRange(Enumerable.Repeat(amount,HotMonsters.ResolveAttackRepeats(in s,(byte)slot,monster,monster.MonsterId,m.MoveId,repeats)));
            }
            foreach(var a in m.Attacks)Hit(a.BaseDamage,a.Repeats);
            if(m.Attacks.Length==0 && (m.BaseDamage>0||m.Repeats>0))Hit(m.BaseDamage,m.Repeats);
            var windows=machine.Nodes.Where(b=>b.NodeKind==HotMonsterNodeKind.RandomBranch).ToDictionary(b=>b.MoveId,b=>b.BranchTargets.Select((t,i)=>new{target=machine.Nodes[t].MoveId,repeat=((MoveRepeatType)b.BranchRepeatTypes[i]).ToString(),max_times=b.BranchMaxTimes[i],cooldown=b.BranchCooldowns[i],allowed_by_history=HotMonsters.ComputeRepeatWeight(in s,side,machine,(byte)slot,t,(MoveRepeatType)b.BranchRepeatTypes[i],b.BranchMaxTimes[i],b.BranchCooldowns[i])>0}).ToArray());
            var registers=new Dictionary<string,int>();
            if(machine.MonsterEntry=="KNOWLEDGE_DEMON")registers["curse_count"]=e.AiRegs[0];
            if(machine.MonsterEntry=="TEST_SUBJECT")registers["respawns"]=e.AiRegs[0];
            if(machine.MonsterEntry=="QUEEN")registers["amalgam_died"]=(e.Flags&HotEnemyFlags.AmalgamDied)!=0?1:0;
            var powers=Powers(slot+3);
            enemies.Add(new{slot=enemies.Count,species=machine.MonsterEntry,hp=e.Vital.CurrentHp,max_hp=e.Vital.MaxHp,block=e.Vital.Block,
                move=m.MoveId,intents=intents.GetValueOrDefault((machine.MonsterEntry,m.MoveId))??[],attack_hits=hits,powers});
            strategicEnemies.Add(slot,new{slot,species=machine.MonsterEntry,hp=e.Vital.CurrentHp,max_hp=e.Vital.MaxHp,block=e.Vital.Block,
                move=m.MoveId,attack_hits=hits,powers,phase=new{node=m.MoveId,rule_ref=machine.MonsterEntry,committed_moves=moves,registers,repeat_windows=windows}});
        }
        var allEnemies=new List<object>();
        for(int i=0;i<s.EnemyCount;i++){
            if(strategicEnemies.TryGetValue(i,out var item))allEnemies.Add(item);
            else{var e=s.Enemies[i];if(e.MonsterDefId!=0)allEnemies.Add(new{slot=i,species=rules.Monsters[e.MonsterDefId].Entry,hp=e.Vital.CurrentHp,max_hp=e.Vital.MaxHp,block=e.Vital.Block,move=(string?)null,phase=(object?)null,attack_hits=Array.Empty<int>(),powers=Powers(i+3)});}
        }
        var legal=actions.Select((a,i)=>{
            bool self=a.Kind==HotActionKind.PlayCard && Target(s,a)==MegaCrit.Sts2.Core.Entities.Cards.TargetType.AnyPlayer;
            return new{index=i,kind=a.Kind.ToString(),card=(int)a.SlotOrHandIdx,
                target=self?0:a.TargetEnemySlot<0?(int?)null:slots[a.TargetEnemySlot],target_side=self?"ally":a.TargetEnemySlot>=0?"enemy":null};
        }).ToArray();
        return new{turn=s.PlayerTurnNumber,round=s.RoundNumber,hp=s.Player.CurrentHp,max_hp=s.Player.MaxHp,block=s.Player.Block,energy=s.Energy,
            stars=s.Stars,gold=s.Gold,draw_count=s.DrawCount,hand=Cards(HotPileKind.Hand),discard=Cards(HotPileKind.Discard),exhaust=Cards(HotPileKind.Exhaust),
            deck,powers=Powers(0),enemies,known_enemies=allEnemies,actions=legal,potion_slots=(int)s.PotionSlotCount,
            played=s.Counters[(int)HotCounterSlot.CardPlayStartsThisTurn],attacks=s.Counters[(int)HotCounterSlot.AttackPlayStartsThisTurn],
            skills=s.Counters[(int)HotCounterSlot.SkillPlayStartsThisTurn],belief=new{counts,top=belief.Top.Select(Name).ToArray(),
                bottom=belief.Bottom.Select(Name).ToArray(),shuffles=belief.Generation}};
    }
}
