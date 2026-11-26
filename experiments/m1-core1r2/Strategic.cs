using CombatSolver;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models.Cards;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    private PileLaw _law=new();
    private object? _observedC;
    private string[] _lastEvents=[];

    private void InitializeLaw()
    {
        var s=InteractiveProperty<SimulationSnapshot>("Current");
        var pc=s.Simulator.State.GetPlayerCombatState(_player);
        _law=new();
        foreach(var c in _player.Deck.Cards) _law.Add($"{c.Id.Entry}#{c.CurrentUpgradeLevel}",1);
        foreach(var c in pc.Hand.Cards.Concat(pc.DiscardPile.Cards).Concat(pc.ExhaustPile.Cards))
            _law.Add(TurnDrawTape.Type(c),-1);
        _law.Check(pc.DrawPile.Cards.Count);
        _law.ShuffleModifier=_player.Deck.Cards.Any(c=>c.Enchantment?.Id.Entry=="PERFECT_FIT");
        if(_player.Deck.Cards.Any(c=>c.Keywords.Contains(CardKeyword.Innate) && _law.Counts.ContainsKey($"{c.Id.Entry}#{c.CurrentUpgradeLevel}")))
            _law.OrderMissing="opening_innate_overflow";
        if(_player.Deck.Cards.Any(c=>c.Enchantment?.ShouldStartAtBottomOfDrawPile==true)) _law.OrderMissing="opening_bottom_modifier";
    }

    // Integration fixture exercises the engine pile API on a fork, independently of card policy.
    private Dictionary<string,object?> PileFixture(SimulationSnapshot root,PileLaw law)
    {
        var sim=root.Simulator;
        var pc=sim.State.GetPlayerCombatState(_player);
        var observations=new List<object>();
        var key=TurnDrawTape.Type(pc.Hand.Cards[1]);
        using var trace=Observer(law,[key],false,false).Enter();
        using var probe=new SearchProbe(true){TurnDraw=trace}.Enter();
        void Save(string operation) {
            var support=trace.Law.Support(pc.DrawPile.Cards.Count);
            observations.Add(new {operation,belief=trace.Law.Export(),support,draw_count=pc.DrawPile.Cards.Count});
        }
        sim.AddToPile(pc.Hand.Cards[0],pc.DrawPile,CardPilePosition.Bottom);Save("bottom");
        sim.AddToPile(pc.Hand.Cards[0],pc.DrawPile,CardPilePosition.Top);Save("top");
        sim.Draw(_player,1);Save("draw");
        sim.CreateAndAddGeneratedCardsToCombat<Wound>(_player,PileType.Draw,1,_player,CardPilePosition.Bottom);Save("fixed_generation");
        sim.Shuffle(_player);Save("shuffle");
        sim.AddToPile(pc.Hand.Cards[0],pc.DrawPile,CardPilePosition.Top);
        sim.AddToPile(pc.Hand.Cards[0],pc.DrawPile,CardPilePosition.Random);Save("order_gap");
        sim.Shuffle(_player);Save("recovered_order");
        return new(){["type"]="core1r2.pile_fixture.v1",["observations"]=observations,["events"]=trace.Events};
    }

    private TurnDrawTape Observer(PileLaw law,string[] prefix,bool stop,bool model)
    {
        var t=new TurnDrawTape(law,prefix){ModelEnemy=model};
        t.AtC=(sim,player,turn,draw,willShuffle,sideStarted,extra)=>{
            var pc=sim.State.GetPlayerCombatState(player);
            var combat=(SimulatedCombatState)sim.State.CombatState;
            var v=sim.State.GetCreature(player.Creature);
            t.Law.Check(pc.DrawPile.Cards.Count);
            object CardState(PredictedCard c)=>new {type=TurnDrawTape.Type(c),cost=c.GetEnergyCostWithModifiers(sim,pc),
                vars=c.Preview.DynamicVars.Values.Where(x=>x.Name is "Damage" or "Block" or "Cards" or "Energy" or "HitCount" or "Repeat"
                    or "StrengthPower" or "DexterityPower" or "VulnerablePower").ToDictionary(x=>x.Name,x=>x.BaseValue)};
            t.Strategic=new {schema="sts2.core.c.v2",turn,round=combat.RoundNumber,hp=v.CurrentHp,max_hp=v.MaxHp,
                block=v.Block,energy=pc.Energy,stars=pc.Stars,gold=combat.GetPlayerGold(player),potions=_root.Frame.Potions,
                powers=combat.EffectivePowers().Where(p=>p.IsVisible && p.Owner==player.Creature)
                    .Select(p=>new {id=p.Id.Entry,amount=p.Amount}).OrderBy(p=>p.id).ToArray(),
                relics=combat.RelicsOf(player).Select(r=>new {id=r.Id.Entry,counter=r.Id.Entry is "NUNCHAKU" or "TUNING_FORK"
                    ?(int?)(combat.ReadRelicCounter(sim,r)%r.DynamicVars.Cards.IntValue):null}).ToArray(),
                card_state=new {hand=pc.Hand.Cards.Select(CardState).ToArray(),
                    discard=pc.DiscardPile.Cards.OrderBy(CardChoiceSupport.ChoiceCardKey,StringComparer.Ordinal).Select(CardState).ToArray(),
                    exhaust=pc.ExhaustPile.Cards.OrderBy(CardChoiceSupport.ChoiceCardKey,StringComparer.Ordinal).Select(CardState).ToArray()},
                hand=pc.Hand.Cards.Select((c,i)=>NoslInstance(c,i,c.GetEnergyCostWithModifiers(sim,pc))).ToArray(),
                discard=PublicPile(pc.DiscardPile.Cards.Select(NoslRow)),exhaust=PublicPile(pc.ExhaustPile.Cards.Select(NoslRow)),
                deck=PublicPile(player.Deck.Cards.Select(c=>new NoslCard(0,c.Id.Entry,c.CurrentUpgradeLevel,null,
                    c.Enchantment?.Id.Entry,c.Enchantment?.Amount,c.Affliction?.Id.Entry,c.Affliction?.Amount))),
                draw_count=pc.DrawPile.Cards.Count,belief=t.Law.Export(),
                enemies=combat.KnownEnemies.Select((e,i)=>new {slot=i,species=e.Monster?.Id.Entry,hp=sim.State.GetCreature(e).CurrentHp,
                    max_hp=sim.State.GetCreature(e).MaxHp,block=sim.State.GetCreature(e).Block,
                    move=e.Monster!=null && sim.State.GetCreature(e).IsAlive?combat.GetPredictedMoveId(e):null,
                    phase=e.Monster!=null && sim.State.GetCreature(e).IsAlive?combat.StrategicPhase(e):null,
                    attack_hits=sim.State.GetCreature(e).IsAlive?CurrentAttackHits(sim,combat,e).ToArray():[],
                    powers=combat.EffectivePowers().Where(p=>p.IsVisible && p.Owner==e).Select(p=>new {id=p.Id.Entry,amount=p.Amount}).OrderBy(p=>p.id).ToArray()
                }).ToArray(),
                setup=new {stage="before_initial_draw",draw,will_shuffle=willShuffle,side_started=sideStarted,extra_turn=extra,
                    completed=new[]{extra?"extra_turn_no_enemy_action":"enemy_side","before_hand_draw","modified_draw_count"},
                    pending=sideStarted?new[]{"hand_draw","draw_hooks","after_player_start","deaths_orbs_autoplay"}:
                        new[]{"hand_draw","draw_hooks","after_player_start","side_start","deaths_orbs_autoplay"}},
                events=t.Events.ToArray(),enemy_models=t.EnemyModels.ToArray()};
            if(stop) SearchProbe.Stop("strategic_c");
        };
        return t;
    }
}
