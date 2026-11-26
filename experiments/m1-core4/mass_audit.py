"""Ensure instrumentation preserves the rollout and sum the two public policy laws."""
from train_value4 import rows,Counter
from core4_roots import Path,sys,json,gzip

def run(out,source):
    original={r["family"]:r for p in out.glob("test-v1-*.gz") for r in rows(p)}
    mass={k:Counter() for k in ("reference_mass","candidate_mass")};queries=0;details=[]
    for r in rows(source):
        b=original[r["family"]]
        assert (r["seed"],r["actions"],r["terminal"],r["states"])==(b["seed"],b["actions"],b["terminal"],b["states"])
        assert len(r["queries"])==len(b["queries"])
        for q,bq in zip(r["queries"],b["queries"]):
            assert all(q[k]==v for k,v in bq.items())
            for k in mass:
                assert abs(sum(q[k].values())-1.)<1e-8
                mass[k].update(q[k])
            queries+=1
        details.append(dict(family=r["family"],policy_laws=[{k:q[k] for k in mass} for q in r["queries"]]))
    assert len(details)==len(original)
    with gzip.open(out/"policy-laws.gz","wt")as f:
        for d in details:f.write(json.dumps(d,separators=(",",":"))+"\n")
    (out/"mass.json").write_text(json.dumps(dict(queries=queries,mass=mass),indent=2))

if __name__=="__main__":run(Path(sys.argv[1]),Path(sys.argv[2]))
