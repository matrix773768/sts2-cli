"""Verify independent panels, issued models, legal-menu invariants and candidate utilization."""
import gzip
import time
from collections import Counter
import numpy as np
from common6 import *
from policy6 import Guide,encode

def main():
    start=time.perf_counter()
    selection=read(E/"selection.json")
    assert selection["panel_sha"]==sha(E/"confirm.gz") and selection["protocol_sha"]==sha(HERE/"protocol.md")
    banned={f for s in json.load(gzip.open(A/"history.gz"))["sources"].values() for f in s["families"]}
    for edition,part in [("train","train"),("dev","dev"),("reserve","train")]:
        banned.update(r["family"] for r in json.load(gzip.open(A/(edition+".gz")))[part])
    banned.update(r["family"] for r in read(HERE.parent/"m1-core5g/evidence/confirmation.json"))
    for n in ("open","confirm"):
        banned.update(r["family"] for r in json.load(gzip.open(HERE.parent/f"m1-core5h/evidence/{n}.gz")))
    panel=json.load(gzip.open(E/"confirm.gz"))
    assert all(r["family"]==digest(sorted(c["id"] for c in r["spec"]["deck"])) and r["family"] not in banned for r in panel)
    for p in E.glob("*.pt"):assert sha(p)==read(p.with_suffix(".json"))["sha256"]
    # Fixed public state: re-indexing the legal menu permutes the scores, and masked rows have no effect.
    actor=Models()
    item=next(read_rows(WORK/"dev-v2-0/public.gz"))["segment"]["steps"][0]
    obs=public_b(item["observation"]["facts"])
    opening=read(HERE.parent/"m1-core5g/evidence/dev-battles.json")[0]["spec"]
    history=actor.g2.encoder.initial_history()
    model=Guide(E/(selection["weight"]+".pt"))
    alpha=model.scores(obs,history,opening)
    rev=obs|dict(actions=[a|dict(index=i) for i,a in enumerate(reversed(obs["actions"]))])
    np.testing.assert_allclose(alpha,model.scores(rev,history,opening)[::-1],atol=4e-5)
    x,c=encode(obs,history,opening)
    with torch.no_grad():
        masked=model.model(torch.tensor(np.vstack([x,x[:1]]))[None],torch.tensor(np.r_[c,c[0]])[None],
                           torch.tensor([[True]*len(x)+[False]]))[0].numpy()
        np.testing.assert_allclose(alpha,masked[:-1],atol=4e-5)
    old=read(HERE.parent/"m1-core5h/evidence/dev-v2-0.json")["rows"]
    new=read(E/"dev-v2-0.json")["rows"]
    assert all(all(x[k]==y[k] for k in ("family","seed","end","status","queries","closed","interventions")) for x,y in zip(old,new,strict=True))
    work={}; files={}
    for arm in [*selection["arms"],"clone"]:
        counts=Counter()
        for i in range(10):
            name=f"confirm-{arm}-{i}";receipt=read(E/(name+".json"))
            directory=WORK/receipt.get("directory",name)
            raw=directory/"engine/natural.jsonl.gz"
            assert sha(raw)==receipt["raw"] and sha(directory/"public.gz")==receipt["public"]
            for r in read_rows(raw):
                assert r["policy_id"]==receipt["policy"]["id"]
                if r["status"]=="failed":
                    assert r["terminal"] is None
                for q in r["queries"]:
                    opt=q["options"]; ref=q["reference_law"]["value"]
                    closed=[o for o in opt if o["value"] is not None]
                    counts["expanded_queries"]+=bool(opt)
                    counts["distinct_first"]+=len({o["index"] for o in opt})
                    counts["closed_first"]+=len({o["index"] for o in closed})
                    if ref is None:
                        counts["options_on_open_reference"]+=len(opt)
                    else:
                        counts["better_closed_options"]+=sum(o["value"]>ref for o in closed)
                        counts["closed_first_on_closed_ref"]+=len({o["index"] for o in closed})
                    if q.get("committed"):
                        counts["changed_first"]+=int(q["selected"]!=q["reference"])
            files[name]=dict(receipt_sha=sha(E/(name+".json")),public=receipt["public"],raw=receipt["raw"])
        work[arm]=counts
    save(E/"audit.json",dict(panel_sha=selection["panel_sha"],excluded=len(banned),history_regression=len(old),weights={p.name:sha(p) for p in E.glob("*.pt")},
                              coverage=work,shards=files,seconds=time.perf_counter()-start))
if __name__=="__main__":main()
