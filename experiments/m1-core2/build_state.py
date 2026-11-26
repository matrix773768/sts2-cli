"""Extend only the public C exporter of the frozen tactical host."""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-core1r2"))
import build

base=build.extension
def extension(solver,sim,host):
    base(solver,sim,host)
    path=host/"Strategic.cs"
    build.replace(path,'schema="sts2.core.c.v2"', 'schema="sts2.core.c.v3"')
    build.replace(path,'potions=_root.Frame.Potions','potions=Enumerable.Range(0,player.PotionSlots.Count).Select(i=>combat.GetPotionAtSlot(player,i)?.Id.Entry).ToArray()')
    build.replace(path,'vars=c.Preview.DynamicVars','cost_layers=CardCostStateSupport.PublicLayers(c.Preview),vars=c.Preview.DynamicVars')
    build.replace(solver/"src/Prediction/CardCostStateSupport.cs","    public static void Append(ref", """    internal static object PublicLayers(CardModel c)=>new {
        energy=c.EnergyCost._localModifiers.Select(m=>new {amount=m.Amount,kind=m.Type.ToString(),expires=m.Expiration.ToString(),reduce_only=m.IsReduceOnly}).ToArray(),
        stars=c._temporaryStarCosts.Select(m=>new {m.Cost,m.ClearsWhenTurnEnds,m.ClearsWhenCardIsPlayed}).ToArray()};
    public static void Append(ref""")
    build.replace(path,':null}).ToArray(),\n                card_state',':r.Id.Entry is "IRON_CLUB" or "JOSS_PAPER" or "HAPPY_FLOWER" or "FAKE_HAPPY_FLOWER" or "PENDULUM" or "POLLINOUS_CORE" or "GALACTIC_DUST" or "MEAT_ON_THE_BONE" ?combat.ReadRelicCounter(sim,r):null}).ToArray(),\n                card_state')
    build.replace(solver/"src/Prediction/MonsterRandomBranchResolver.cs","    private static float RepeatWeight","    internal static float RepeatWeight")
    build.replace(solver/"src/Search/SimulatedCombatState.MonsterAi.cs","return new {node=state.Current.Id,", """var repeatWindows=state.Machine.States.Values.OfType<MegaCrit.Sts2.Core.MonsterMoves.MonsterMoveStateMachine.RandomBranchState>()
            .ToDictionary(b=>b.Id,b=>b.States.Select(x=>new {target=x.stateId,repeat=x.repeatType.ToString(),x.maxTimes,x.cooldown,
                allowed_by_history=MonsterRandomBranchResolver.RepeatWeight(state.Machine,x,state.StateLog)>0}).ToArray());
        return new {node=state.Current.Id,repeat_windows=repeatWindows,""")
    build.replace(host/"Tactical.cs",'if(mode=="pile_fixture")', '''if(mode=="cost_fixture"){
                    var pc=root.Simulator.State.GetPlayerCombatState(owner._player);
                    var card=pc.Hand.Cards[0];
                    card.MutablePreview.EnergyCost.SetThisCombat(2);
                    card.MutablePreview.EnergyCost.SetThisTurn(0);
                    var other=pc.Hand.Cards[1];
                    other.MutablePreview.EnergyCost.SetThisTurn(0);
                    object Read(PredictedCard c)=>new {cost=c.GetEnergyCostWithModifiers(root.Simulator,pc),layers=CardCostStateSupport.PublicLayers(c.Preview)};
                    var before=new[]{Read(card),Read(other)};
                    card.MutablePreview.EndOfTurnCleanup();
                    other.MutablePreview.EndOfTurnCleanup();
                    return new(){["before"]=before,["after"]=new[]{Read(card),Read(other)}};
                }
                if(mode=="pile_fixture")''')
def manifest(out):
    import json
    path=out/"build.json"
    record=json.loads(path.read_bytes())
    record["core2_generated_sources"]={name:build.source_sha(out/name) for name in (
        "host/Headless/Strategic.cs","host/Headless/Tactical.cs","solver/src/Prediction/CardCostStateSupport.cs",
        "solver/src/Search/SimulatedCombatState.MonsterAi.cs","solver/src/Prediction/MonsterRandomBranchResolver.cs")}
    return record

if __name__=="__main__":
    import json
    build.extension=extension
    out=Path(sys.argv[1]).resolve()
    build.build(out,None)
    (out/"build.json").write_text(json.dumps(manifest(out),indent=2))
