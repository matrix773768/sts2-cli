"""Verify local DC1 evidence and generate its compact reproducible index."""
import argparse
from collections import Counter
from contextlib import closing
from itertools import combinations
from pathlib import Path
import sqlite3

from dc_common import HERE, ROOT, arms, checksum, config, digest, read, write_json
from dc_roots import BASIC
from loop_roots import composition


def verify_roots(root, cfg):
    directory = root/"roots"
    identity = read(directory/"identity.json")
    if identity["config"] != cfg:
        raise ValueError("Published configuration differs from frozen roots")
    for name, expected in identity["files"].items():
        if checksum(directory/name) != expected:
            raise ValueError(f"Frozen root fingerprint differs: {name}")
    families = read(directory/"families.json")
    indexed = {family["id"]:family for family in families}
    deck_ids = {family["deck_family"] for family in families}
    if len(indexed) != len(families) or len(deck_ids) != len(families):
        raise ValueError("Frozen pool identity collision")
    seeds, sizes = set(), {}
    by_pool = {}
    for pool,(size,repeats) in cfg["pools"].items():
        by_pool[pool] = [f for f in families if f["split"] == pool]
        if len(by_pool[pool]) != size:
            raise ValueError(f"Frozen family count differs: {pool}")
        jobs = read(directory/f"{pool}.json")["jobs"]
        expected = {i:f["id"] for f in by_pool[pool] for i in f["worlds"]}
        if (len(jobs) != size*repeats or len(expected) != len(jobs)
                or any(len(f["worlds"]) != repeats for f in by_pool[pool])):
            raise ValueError(f"Invalid world count: {pool}")
        for i,spec,split,family,room in jobs:
            f = indexed[family]
            if (split != pool or f["split"] != pool or f["room"] != room or expected[i] != family
                    or spec["seed"] in seeds or digest(composition(spec)) != f["deck_family"]
                    or {k:v for k,v in spec.items() if k!="seed"} != f["spec"]):
                raise ValueError(f"Invalid frozen world: {pool}/{i}")
            seeds.add(spec["seed"])
        sizes[pool] = [size,repeats]
    deck = lambda f: Counter(c["id"] for c in f["spec"]["deck"] if c["id"] not in BASIC)
    maximum = 0.
    for left,right in combinations(by_pool.values(),2):
        for a in map(deck,left):
            for b in map(deck,right):
                maximum=max(maximum,sum((a&b).values())/max(1,sum((a|b).values())))
    if maximum > cfg["near_duplicate_jaccard"]:
        raise ValueError("Near-duplicate decks cross isolated pools")
    return dict(host=identity["host"], config=identity["config"], manifests=identity["files"],
                historical_exclusions=identity["excluded"], sizes=sizes, seeds=len(seeds), max_cross_split_jaccard=maximum)


def relative(path):
    return path.relative_to(ROOT).as_posix()


def reference(path):
    return dict(path=relative(path),sha256=checksum(path))


def summarize_ledger(path):
    database = path/"results.sqlite"
    with closing(sqlite3.connect(database.resolve().as_uri()+"?mode=ro", uri=True)) as db:
        identity, = db.execute("select sha from contract").fetchone()
        n, = db.execute("select count(*) from results").fetchone()
        sessions, wall_s = db.execute("select count(*),sum(seconds) from sessions").fetchone()
    summary = read(path/"summary.json")
    if n != summary["attempts"]:
        raise ValueError(f"Incomplete summary: {path}")
    result = dict(identity=identity, records=n, sessions=sessions, wall_s=wall_s, statuses=summary["status"],
                  counts={k:v for k,v in summary["counts"].items() if k in
                          ("terminal_mismatch","public_mismatch","wire_or_root_mismatch","stop_wall_cap")},
                  database=reference(database), summary=reference(path/"summary.json"))
    wal = database.with_name("results.sqlite-wal")
    if wal.exists() and wal.stat().st_size:
        result["wal"] = reference(wal)
    return result


def build(root):
    cfg = config()
    frozen = verify_roots(root,cfg)
    data = read(root/"results.json")["pools"]
    accountability = {}
    for pool,(n,repeats) in cfg["pools"].items():
        for arm in cfg["arms"]:
            arm_path = root/"evaluation"/pool/arm
            proof = summarize_ledger(arm_path)
            if proof["records"] != n*repeats:
                raise ValueError(f"Partial formal cohort: {arm_path}")
            accountability[f"{pool}/{arm}"] = proof
        for arm in ("D0","S0","S2"):
            proof = summarize_ledger(root/"evaluation"/f"{pool}-controls"/arm)
            if proof["records"] != cfg["control_families_per_pool"]*repeats:
                raise ValueError(f"Incomplete control: {pool}/{arm}")
            accountability[f"{pool}-controls/{arm}"] = proof
    for name in ("smoke","diagnostics","utility","production"):
        for file in sorted((root/name).glob("**/results.sqlite")):
            accountability[file.parent.relative_to(root).as_posix()] = summarize_ledger(file.parent)
    for name in ("D2", "D2-search"):
        smoke = accountability[f"smoke/{name}"]
        if smoke["sessions"] != 2 or smoke["records"] != 32:
            raise ValueError("Missing resume smoke evidence")
    production = accountability["production/round-1/D2"]
    if production["sessions"] != 2 or production["records"] != 32:
        raise ValueError("Missing training production resume evidence")
    reports = [root/p for p in ("results.json","family-analysis.json","history.json","classification-protocol.json",
                 "curriculum.json","diagnostics/summary.json","utility/summary.json","historical-labels.jsonl.gz",
                 "production/round-1/manifest.json","roots/identity.json")]
    by_pool = {pool:dict(direct=rows["overall"]["direct"]["statuses"],search=rows["overall"]["search"]["statuses"],
                         quadrants=rows["by_quadrant"]) for pool,rows in data.items()}
    return dict(kind=cfg["version"], base_commit="f733c7aaa961ef15dbe821a999944a4dd0820a75",
                root=relative(root), frozen=frozen, sources={p.name:checksum(p) for p in sorted(HERE.iterdir())
                                                            if p.suffix==".py" or p.name=="config.json"},
                arms={k:dict(model=reference(p),condition=condition,budget=budget)
                      for k,(p,condition,budget) in arms().items()}, primary_counts=by_pool,
                ledgers=accountability, reports=[reference(path) for path in reports])


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("root", type=Path)
    cli.add_argument("index", type=Path)
    args = cli.parse_args()
    write_json(args.index,build(args.root.resolve()))
