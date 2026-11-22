"""Export staged II-K acceptance and gate on actual per-root preservation."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import runpy
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / "m1-nosl3c-iij5b"
BASE = runpy.run_path(str(PREVIOUS / "export_evidence.py"))
read, ledger, exact, compare = [BASE[k] for k in ("read", "ledger", "exact", "compare_proofs")]
OLD = read(PREVIOUS / "evidence.json")
LOGS = Path("logs")
CASES = {
    "pair16": {(0,"000001"): "iik4b-resample/0-000001", (0,"000006"): "iik21-resample/pair16/0-000006",
               (0,"000009"): "iik1-resample/0-000009", (0,"000014"): "iik3b-resample/pair16-0-000014/0-000014"},
    "holdout": {(0,"000014"): "iik3b-resample/holdout-0-000014/0-000014",
                (0,"000023"): "iik24-resample/0-000023", (0,"000027"): "iik3b-resample/holdout-0-000027/0-000027",
                (1,"000010"): "iik21-resample/holdout/1-000010", (1,"000013"): "iik3b-resample/holdout-1-000013/1-000013",
                (1,"000020"): "iik22-resample/1-000020", (1,"000021"): "iik23-resample/1-000021"},
}


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def proof(raw):
    return {k: raw[k] for k in ("status", "certification", "terminal_verified", "native_terminal_stamp",
                               "boundaries", "reason", "first_failure", "position",
                               "continuation_fields", "prediction_stop_detail", "detail") if k in raw}


def route_changes(before, after):
    diff = BASE["B"]["BASE"]["first_changes"](before, after)
    if "observation" in diff:
        a = diff["observation"]
        for key, steps in (("before", before), ("after", after)):
            a[key] = {field: steps[a["index"]]["observation"].get(field) for field in a["fields"]}
    return diff


def suite(folder, name, engine):
    previous = LOGS / f"iij5b-serial-{name}"
    old_id, old_snap, old_rows = ledger(previous / "training.sqlite")
    identity, snaps, rows = ledger(folder / "training.sqlite")
    assert identity["engine"] == engine and old_id["config"] == identity["config"]
    assert old_snap[0][:3] == snaps[0][:3]
    assert read(previous / "course-roots.json") == read(folder / "course-roots.json")
    assert read(folder / "report.json")["optimizer"] == {}
    result = []
    for old, new in zip(old_rows, rows, strict=True):
        _, step, root, status, spec, policy_rows = new
        assert old[:3] == new[:3] and old[4] == spec
        before, after = [items[0] if items else {} for items in (old[5], policy_rows)]
        assert before.get("behavior") == after.get("behavior")
        filename = f"{step:06d}-{root}.json"
        prior, current = [proof(read(d / "audit" / filename)) for d in (previous, folder)]
        data = dict(step=step, root=root, old=prior, new=current, retained=compare(prior,current),
                    classification=status, behavior=after.get("behavior"), decisions=len(after.get("transitions", [])),
                    changes=route_changes(before.get("transitions", []), after.get("transitions", [])))
        if (step, root) in CASES[name]:
            archived = read(LOGS / (CASES[name][step,root] + ".json"))
            expected = proof(archived["evidence"])
            data["targeted"] = dict(proof=expected, changes=route_changes(archived["rows"][0]["transitions"],
                                                                        after.get("transitions", [])))
        result.append(data)
    return result


def collect(prefix):
    folder = lambda name: LOGS / f"{prefix}-{name}"
    times = [read(p) for p in sorted(LOGS.glob(f"{prefix}-*-time.json"))]
    main = LOGS / "iik5-main-host/bin/Debug/net9.0"
    combat = LOGS / "iik4b-host-final/Headless/bin/Debug/net9.0"
    result = dict(timings=times, artifacts={str(p): digest(p) for p in (
        main / "Sts2Headless.dll", main / "GodotSharp.dll",
        combat / "OfflineSearchHarness.dll", combat / "GodotSharp.dll", LOGS / "iik3b-solver/bin/CombatSolver.dll")})
    result["fixtures"] = {name: {p.name: read(p) for p in folder(name).glob("*.json")}
                          for name in ("orb","rod","glass","suck","cards","osty","boulder")}
    if (LOGS / f"{prefix}-signals.log").exists():
        result["signals"] = (LOGS / f"{prefix}-signals.log").read_text(encoding="utf-8").strip()
    summary = folder("archive") / "summary.json"
    if not summary.exists():
        return result
    engine = result["engine"] = read(summary)["versions"]
    archive = result["history"] = BASE["frozen"](prefix, OLD, engine)
    gates = result["gates"] = {
        "history": len(archive) == 65 and sum(exact(r["proof"]) for r in archive) == 42
        and all(r["retained"] and r["classification"] == r["baseline"]
                and r["category"] == r["baseline_category"] for r in archive)
    }
    if (folder("prefix") / "prefix.json").exists():
        current = read(folder("prefix") / "prefix.json")
        old = OLD["risk_prefixes"]
        assert current["engine"] == engine
        signatures = lambda rows: {(r["ledger"], r["step"], r["root"]):
                                   (r["status"], [(s["position"], s.get("stamp")) for s in r["steps"]]) for r in rows}
        result["prefixes"] = current["results"]
        gates["prefixes"] = signatures(old) == signatures(current["results"])
    groups = BASE["A"]["GROUPS"]
    if all((folder(f"sample-{n}") / "report.json").exists() for n in groups):
        originals = {(r["ledger"],r["step"],r["root"]): r for r in OLD["resampled"]}
        result["samples"] = samples = []
        for group, roots in groups.items():
            ident, rows = BASE["A"]["sample"](folder(f"sample-{group}"))
            assert ident["engine"] == engine and read(folder(f"sample-{group}") / "report.json")["optimizer"] == {}
            for key, row in zip(roots, rows, strict=True):
                previous = originals[key]
                before = previous["observed"]
                assert ident["config"] == previous["config_sha256"]
                samples.append(dict(root=key, before=before["audit"], after=row["audit"], behavior=row["behavior"],
                                    matched=all(row[k]==before[k] for k in ("spec","behavior","root_sha256"))
                                    and compare(before["audit"],row["audit"])))
        gates["samples"] = (Counter(r["after"]["status"] for r in samples)
                            == {"admissible_predicted_win": 3, "admissible_death": 5}
                            and all(r["matched"] and exact(r["after"]) for r in samples))
    for name, expected in (("pair16", (15,1)), ("holdout", (37,22))):
        if not (folder(name) / "report.json").exists():
            continue
        rows = result[name] = suite(folder(name), name, engine)
        totals = Counter(r["new"]["status"] for r in rows if exact(r["new"]))
        status = ("admissible_predicted_win","admissible_death")
        gates[name] = tuple(totals[s] for s in status)==expected and all(r["retained"] for r in rows)
        gates[name] &= all(exact(r["new"]) and all(r["targeted"]["proof"].get(k) == r["new"].get(k)
                               for k in ("status", "boundaries", "native_terminal_stamp"))
                           and not r["targeted"]["changes"] for r in rows if "targeted" in r)
        if name == "holdout":
            axebot = next(r for r in rows if (r["step"],r["root"])==(1,"000029"))
            gates[name] &= axebot["new"]["status"]=="truncated" and axebot["new"]["reason"]=="action_cap"
    if (LOGS / f"{prefix}-journals.json").exists():
        training = result["training"] = BASE["B"]["training"](prefix, engine)
        training["final_model_sha256"] = training["snapshots"][-1]["stats"]["model_sha256"]
        c = training["comparison"]
        gates["training"] = c["roots"]==32 and c["snapshots"]==3 and all(c[k] for k in (
            "identity_equal","snapshots_equal","semantic_rows_equal"))
    if (LOGS / f"{prefix}-main.xml").exists():
        counts, details = Counter(), []
        for item in ET.parse(LOGS / f"{prefix}-main.xml").iter("testcase"):
            status = next((s for s in ("failure","error","skipped") if item.find(s) is not None),"passed")
            counts[status] += 1
            if status != "passed" or item.attrib["classname"].endswith("TestLanguage"):
                node = item.find(status)
                details.append(dict(status=status, detail=node.get("message") if node is not None else None,
                                    **item.attrib))
        result["main"] = dict(counts=counts, cases=details)
        gates["main"] = counts=={"passed":164,"skipped":1} and all(r["status"]=="passed" for r in details
                                                                if r["classname"].endswith("TestLanguage"))
    return result


if __name__ == "__main__":
    prefix, destination = sys.argv[1:3]
    result = collect(prefix)
    Path(destination).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(result.get("gates"))
    if not all(result.get("gates", {}).values()):
        sys.exit(1)
