"""Post-confirmation encounter transfer. Held-out enemy identities are used only to assign fixtures."""
from play_loop import *
from study_metrics import paired,describe
from train_value4 import rows
from state import static_rules

ENCOUNTERS={"HAUNTED_SHIP_NORMAL":"HAUNTED_SHIP","NIBBITS_NORMAL":"NIBBIT"}
def collect(out,mode,encounter,netpath):
    out.mkdir(parents=True,exist_ok=False);t=perf_counter()
    host,model=setup(out);lane=Lane(host,0);net=load_net(netpath,mode)
    donor=next(j[1] for j in panels()["confirm"] if j[1]["encounter"]==encounter)
    with gzip.open(out/"rows.gz","wt") as f:
        for j in panels()["confirm"]:
            spec=spec_for(j,"transfer-"+encounter)|{k:donor[k] for k in ("act","act_variant","encounter")}
            try:
                r=fight(lane,model,spec,mode,net);lane.reset()
            except (RuntimeError,ValueError,KeyError,IndexError) as e:
                lane.close();r=dict(states=[],terminal=None,error=repr(e))
            f.write(json.dumps(r|dict(family=j[3],seed=spec["seed"],hp=spec["hp"],max_hp=spec["max_hp"],
                policy=mode,encounter=encounter),separators=(",",":"))+"\n")
    lane.close();host.close();(out/"seconds.json").write_text(json.dumps(perf_counter()-t))

def summarize(logs,out):
    from shutil import copyfile
    summary={}
    for encounter,species in ENCOUNTERS.items():
        allrows={}
        for arm in ("v1","G2"):
            source=logs/f"c4-transfer-legal-{encounter}-{arm}";dst=out/f"transfer-{encounter}-{arm}.gz"
            copyfile(source/"rows.gz",dst);allrows[arm]=list(rows(dst))
        base={(r["family"],r["seed"]):r for r in allrows["G2"]}
        summary[encounter]=dict(eligible=paired(allrows["v1"],base),G2=describe(allrows["G2"]),v1=describe(allrows["v1"]),
            species_in_catalog=species in static_rules()["graphs"],g2_wins=sum(r.get("status")=="predicted_win"for r in allrows["G2"]),
            qualified=sum(q["reference_coverage"]>=1-1e-9 for r in allrows["v1"]for q in r.get("queries",[])))
    (out/"transfer.json").write_text(json.dumps(summary,indent=2))
if __name__=="__main__":
    if sys.argv[1]=="summarize":summarize(Path(sys.argv[2]),Path(sys.argv[3]))
    else:collect(Path(sys.argv[1]),*sys.argv[2:])
