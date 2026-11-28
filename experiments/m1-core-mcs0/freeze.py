"""Freeze public root selection independently of all search measurements."""
from pathlib import Path
import json, gzip, hashlib
from collections import defaultdict

H = Path(__file__).resolve().parent
E = H / "evidence"
OLD = H.parent / "m1-core6b1/evidence"
CORE = H.parents[1]

def digest(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def read(p):
    return json.loads(p.read_bytes())

def gz(p):
    with gzip.open(p) as f:
        return json.load(f)

def save(name, data):
    (E/name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf8")

def sources():
    return gz(E/"roots.gz")

def main():
    roots = gz(OLD/"prefixes.gz")
    rows = read(OLD/"panel.json")["roots"]
    dev = CORE/"logs/core6a/dev-low-0"
    receipt = read(H.parent/"m1-core6a/evidence/dev-low-0.json")
    assert hashlib.sha256((dev/"public.gz").read_bytes()).hexdigest() == receipt["public"]
    strata = defaultdict(list)
    taken = {r["family"] for r in rows}
    with gzip.open(dev/"public.gz") as stream:
        for job, line in zip(read(dev/"jobs.json"), stream, strict=True):
            spec = job["spec"]
            view = json.loads(line)
            assert view["seed"] == spec["seed"]
            if job["family"] in taken:
                continue
            steps = view["segment"]["steps"]
            starts = {}
            for i, x in enumerate(steps):
                o = x["observation"]
                if o["status"] == "active":
                    starts.setdefault(o["facts"]["turn"], i)
            if not starts:
                continue
            j = min(starts.values(), key=lambda i: digest(["mcs0-turn",job["family"],i]))
            enc = spec["encounter"]
            kind = "elite" if "ELITE" in enc else "boss" if "BOSS" in enc else "other"
            strata[spec["act"],kind].append((digest(["mcs0-family",job["family"]]),job,j,steps))
    for values in strata.values():
        values.sort(key=lambda x:x[0], reverse=True)
    while len(rows) < 64:
        before = len(rows)
        for group in sorted(strata):
            if not strata[group] or len(rows) == 64:
                continue
            _, job, j, steps = strata[group].pop()
            if job["family"] in taken:
                continue
            taken.add(job["family"])
            id_ = f"dev-{len(rows)-39:02}"
            o = steps[j]["observation"]
            roots[id_] = dict(spec=job["spec"], steps=steps[:j], root=o)
            rows.append(dict(id=id_, family=job["family"], source="6A dev-low-0", group="dev",
                             turn=o["facts"]["turn"], view=o["view"], index=j))
        assert len(rows)>before
    for r in rows:
        root = roots[r["id"]]
        f = root["root"]["facts"]
        spec = root["spec"]
        r.update(seed=spec["seed"],act=spec["act"],encounter=spec["encounter"],deck_size=len(spec["deck"]),
                 hand=len(f["hand"]),energy=f["energy"],legal=len(f["actions"]),enemies=f["enemies"],
                 powers=f["powers"],relics=spec["relics"],prefix_sha256=digest(root["steps"]))
        cards = [f["hand"][a["card"]] for a in f["actions"] if a["kind"]=="PlayCard"]
        r["flags"] = sorted({label for c in cards for label,yes in {
            "draw":c["vars"].get("Cards",0)>0,"energy":c["vars"].get("Energy",0)>0,
            "X":c["energy_x"],"cost_layer":bool(c["cost_mods"]),
            "multi_enemy":len(f["enemies"])>1}.items() if yes})
    assert len(roots)==len(rows)==64
    (E/"roots.gz").write_bytes(gzip.compress(json.dumps(roots,separators=(",",":")).encode(),mtime=0))
    save("panel.json",rows)

if __name__ == "__main__":
    main()
