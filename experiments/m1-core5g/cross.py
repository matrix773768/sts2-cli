"""Cross one complete differing development turn with each of two continuations."""
import json,time
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("battle5g",Path(__file__).with_name("battle.py"))
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
E,W,Models,Evaluator,Value,torch,hot,read_rows,check_battle,sha=(
    runner.E,runner.W,runner.Models,runner.Evaluator,runner.Value,runner.torch,
    runner.hot,runner.read_rows,runner.check_battle,runner.sha)

def blank():
    return dict(states=[],queries=[],trace=[],choices=[],actual_steps=0,terminal=None)

def main():
    tick=time.perf_counter()
    challenger=json.loads((E/"selection.json").read_bytes())["primary"]
    arms=["v2",challenger]
    panels=json.loads((E/"dev-battles.json").read_bytes())
    archive=[list(read_rows(W/f"dev-{a}-0"/"natural.jsonl.gz")) for a in arms]
    models=[Models(),Models()]
    path=E/(challenger+".pt")
    assert sha(path)==json.loads((E/(challenger+".json")).read_bytes())["sha256"]
    net=Value()
    net.load_state_dict(torch.load(path,weights_only=True))
    models[1].evaluate=Evaluator(net.eval())
    cases=[]
    client=hot.Client(W/"cross-transport")
    try:
        # Take the first eligible development win flip in each direction by preregistered panel order.
        for direction in [("Defeat","Victory"),("Victory","Defeat")]:
            for i,(a,b) in enumerate(zip(*archive)):
                if (a["status"],b["status"])!=direction:continue
                turn=next((x[0] for x,y in zip(a["trace"],b["trace"]) if x!=y),None)
                if turn is None:continue
                qs=[next((q for q in r["queries"] if q["turn"]==turn),{}) for r in (a,b)]
                if not all("policy" in q for q in qs):continue
                spec=panels[i]["spec"]
                outcomes=[]
                for plan,q in enumerate(qs):
                    for j,m in enumerate(models):
                        pre=blank()
                        state,history=hot.fight(client,spec,models[0],"tactical",32,pre,until=turn,require_match=True)
                        assert pre["trace"]==[x for x in a["trace"] if x[0]<turn]==[x for x in b["trace"] if x[0]<turn]
                        assert pre["choices"]==[x for x in a["choices"] if x["turn"]<turn]==[x for x in b["choices"] if x["turn"]<turn]
                        row=blank()
                        try:
                            hot.fight(client,spec,m,"tactical",32,row,resume=(state,history),first=q["selected"],
                                      intervention_law=q["law"],intervention_policy=q["policy"],require_match=True)
                            check_battle(row,dict(policy=q["policy"],first=q["selected"]))
                        except (ValueError,RuntimeError,TimeoutError) as e:
                            row.update(status="failed",reason=str(e),terminal=None)
                        hp=row["terminal"]["hp"] if row["terminal"] else None
                        if plan==j:assert (row["status"],hp)==(archive[j][i]["status"],archive[j][i]["terminal"]["hp"])
                        outcomes.append(dict(plan=arms[plan],suffix=arms[j],status=row["status"],hp=hp,reason=row.get("reason")))
                cases.append(dict(root=i,turn=turn,encounter=spec["encounter"],seed=spec["seed"],outcomes=outcomes))
                break
    finally:client.close()
    (E/"cross.json").write_text(json.dumps(dict(seconds=time.perf_counter()-tick,cases=cases),indent=2))
if __name__=="__main__":main()
