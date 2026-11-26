"""Fixed development fights under one public continuation plus archived policy distributions."""
from time import perf_counter
import argparse
import zipfile
from state import *
from search import Lane,cohort,host_at,step,read,digest

POLICY="first-legal-card-else-end/public-v1"
def run(out,build):
    out.mkdir(parents=True,exist_ok=False)
    start=perf_counter()
    host=host_at(out,build.resolve())
    summary=[]
    archive=HERE.parent/"m1-core1r2/evidence/panel.zip"
    benchmark=read(HERE.parent/"m1-core1/benchmark.json")
    jobs=[j for j in benchmark["jobs"] if j["split"]=="development"]
    with gzip.open(out/"records.jsonl.gz","wt",encoding="utf8") as dst,zipfile.ZipFile(archive) as z:
        def emit(row):dst.write(json.dumps(row,separators=(",",":"))+"\n")
        panel=json.loads(z.read("panel.json"))
        for row in panel["rows"]:
            family=row["family"]
            d=json.loads(gzip.decompress(z.read(family+".json.gz")))
            for q in d["queries"]:
                p=q["position"]
                emit(dict(family=family,source="public_policy",position=p,history=d["history"][:p],
                    root=q["graph"]["nodes"][0]["state"],policy=q["policy"],graph_ref=[family,p],
                    continuation=None,distribution=list(distribution(q["settlement"]["successors"]))))
        for job in jobs:
            lane=Lane(host,0)
            captured=[]
            history=[]
            try:
                st=cohort.start(lane,job["spec"])
                while st["status"]=="active" and len(history)<128:
                    o=host.project(st["observation"])
                    menu=o["actions"]
                    a=next((a for a in menu if a["kind"]=="confirm_selection"),menu[0])
                    history.append([o,a["index"]])
                    st=step(lane,st,a["index"])
                    if st.get("observed_c"):captured.append((len(history),st["observed_c"]))
                terminal=None
                if st["status"] in ("predicted_win","death"):
                    t=st["terminal_observation"]
                    terminal=dict(status=st["status"],hp=t["hp"],max_hp=t["max_hp"],potions=t["potions"],
                                  gold=(st.get("result") or {}).get("gold"))
                emit(dict(source="trajectory",family=job["family"],continuation=POLICY,history=history,terminal=terminal))
                for pos,c in captured:
                    emit(dict(source="natural",family=job["family"],position=pos,continuation=POLICY,
                        features=encode(c),terminal=terminal,net_hp=c["hp"]-terminal["hp"] if terminal else None))
                summary.append(dict(family=job["family"],status=st["status"],actions=len(history),states=len(captured)))
            finally:lane.close()
    host.close()
    (out/"ledger.json").write_text(json.dumps(dict(seconds=perf_counter()-start,runs=summary,training_updates=0),indent=2))
if __name__=="__main__":
    run(Path(sys.argv[1]),Path(sys.argv[2]))
