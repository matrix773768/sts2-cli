"""Recompute panel coverage, dynamic constraints and matched-intent contrast with actual next C."""
from core2_dataset import *
from statistics import median

def measure(folder):
    start=perf_counter()
    all_rows=[r for b in batches(folder/"records.jsonl.gz") for r in b]
    natural=[r for r in all_rows if r["source"]=="natural"]
    states=[r["features"]["state"] for r in natural]
    start_encode=perf_counter()
    for c in states:enrich(c)
    encode_seconds=perf_counter()-start_encode
    examples={}
    contrast=None
    qualified=removed=actual_allowed=actual_checked=0
    groups={}
    for r in natural:groups.setdefault(r["family"],[]).append(r)
    for family,rows in groups.items():
        for a,b in zip(rows,rows[1:]):
            left,right=(r["features"]["state"] for r in (a,b))
            for e in left["enemies"]:
                following=next((f for f in right["enemies"] if f["slot"]==e["slot"] and f["species"]==e["species"] and f.get("move")),None)
                if not following or not e.get("move"):continue
                pressure=enrich(left)["pressure"][e["slot"]]
                allowed=pressure.get("history_allowed")
                if allowed is not None:
                    actual_checked+=1
                    actual_allowed+=following["move"] in allowed
                key=tuple(e["attack_hits"])
                if not key or sum(key)==0:continue
                sample=dict(family=family,turn=left["turn"],species=e["species"],slot=e["slot"],move=e["move"],
                    hits=key,next_move=following["move"],next_hits=following["attack_hits"])
                if contrast is None and key in examples and examples[key]["next_hits"]!=sample["next_hits"]:
                    contrast=[examples[key],sample]
                examples[key]=sample
    for c in states:
        for p in enrich(c)["pressure"]:
            if "history_allowed" in p:
                qualified+=1
                removed+=len(p["history_allowed"])<len(p["possible_targets"])
    strict=[r for batch in strict_batches() for r in batch]
    labels=list(learning_batches(folder/"records.jsonl.gz"))
    return dict(families=len(groups),states=len(states),labeled=sum(map(len,labels)),
        outcomes=dict(Counter(r["terminal"]["status"] for r in all_rows if r["source"]=="trajectory")),
        strict_queries=len(strict),strict_mass=sum(x["weight"] for r in strict for x in r["distribution"] if x["qualification"]=="C"),
        history_windows=qualified,windows_narrowed=removed,observed_next_in_window=[actual_allowed,actual_checked],
        attack_contrast=contrast,encode_seconds=encode_seconds,median_json_bytes=median(len(json.dumps(enrich(c),separators=(",",":")).encode()) for c in states),
        seconds=perf_counter()-start)
if __name__=="__main__":
    folder=Path(sys.argv[1])
    (folder/"summary.json").write_text(json.dumps(measure(folder),indent=2))
