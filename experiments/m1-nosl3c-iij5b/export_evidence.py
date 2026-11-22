"""Compare II-J.5B against the frozen II-I.9A/9B evidence."""
import argparse
from collections import Counter
from contextlib import closing
from hashlib import sha256
import gzip
import json
from pathlib import Path
import runpy
import sqlite3
import subprocess
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
A = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii9a/export_evidence.py"))
B = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii9b/export_evidence.py"))
read, ledger, proof = (B[key] for key in ("read", "ledger", "proof"))
STAMP = "native_terminal_stamp"


def exact(p):
    return p.get("certification") == "exact_native_match" and p.get("terminal_verified") is True


def compare_proofs(old, new):
    return not exact(old) or (exact(new) and (old.get("status"), old.get(STAMP)) ==
                              (new.get("status"), new.get(STAMP)))


def timings(folder):
    path = (folder / "training.sqlite").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(path, uri=True)) as db:
        return {(step, root): json.loads(gzip.decompress(blob)).get("timing", {})
                for step, root, blob in db.execute("SELECT step,root,rows FROM roots")}


def suite(prefix, name, count, engine):
    old_dir, new_dir = (Path("logs") / f"{tag}-{name}" for tag in ("iii9b", prefix))
    old_id, old_snapshots, old = ledger(old_dir / "training.sqlite")
    new_id, new_snapshots, new = ledger(new_dir / "training.sqlite")
    assert new_id["engine"] == engine and len(old) == len(new) == count
    assert old_id["config"] == new_id["config"]
    assert read(old_dir / "course-roots.json") == read(new_dir / "course-roots.json")
    assert old_snapshots[0][:3] == new_snapshots[0][:3]
    old_time, new_time = timings(old_dir), timings(new_dir)
    data = []
    for a, b in zip(old, new, strict=True):
        _, step, root, status, spec, rows = b
        assert a[:3] == b[:3] and a[4] == spec
        before, after = (row[0] if row else {} for row in (a[5], rows))
        if before and after:
            assert before["behavior"] == after["behavior"]
        early, late = (row.get("transitions", []) for row in (before, after))
        changes = B["BASE"]["first_changes"](early, late)
        if "observation" in changes:
            detail = changes["observation"]
            index = detail["index"]
            for key, transitions in (("expected", early), ("actual", late)):
                detail[key] = {k: transitions[index]["observation"].get(k) for k in detail["fields"]}
        if len(early) != len(late):
            index = min(len(early), len(late))
            changes["first_unpaired"] = dict(index=index, expected=B["decision"](early[index])
                if index < len(early) else None, actual=B["decision"](late[index])
                if index < len(late) else None)
        old_raw, new_raw = (read(folder / "audit" / f"{step:06d}-{root}.json")
                            for folder in (old_dir, new_dir))
        old_proof, new_proof = (proof(folder, step, root) for folder in (old_dir, new_dir))
        old_proof["route"], new_proof["route"] = old_raw.get("route"), new_raw.get("route")
        for detail in ("position", "fields", "native_before", "native_after"):
            if detail in new_raw and not exact(new_proof):
                new_proof[detail] = new_raw[detail]
        data.append(dict(step=step, root=root, baseline=a[3], classification=status,
                         baseline_proof=old_proof, proof=new_proof, decisions=len(late),
                         baseline_decisions=len(early), first_changes=changes,
                         baseline_timing=old_time[step, root], timing=new_time[step, root],
                         behavior=after.get("behavior"), feedback=after.get("feedback"),
                         retained=compare_proofs(old_proof, new_proof)))
    assert read(new_dir / "report.json")["optimizer"] == {}
    return dict(config_sha256=new_id["config"], initial_snapshot_sha256=new_snapshots[0][1], roots=data)


def frozen(prefix, old, engine):
    folder = Path("logs") / f"{prefix}-archive"
    assert read(folder / "summary.json")["versions"] == engine
    data = []
    for prior in old["history"]:
        file = folder / f"{prior['ledger']}.json"
        current = next(row for row in read(file) if (row["step"], row["position"]) ==
                       (prior["step"], prior["position"]))
        assert prior["root"] == current["root"]
        old_p, new = prior["proof"], current.get("result", {})
        data.append(dict(ledger=prior["ledger"], step=prior["step"], root=prior["root"],
                         position=prior["position"], baseline=prior["classification"],
                         classification=current["native_classification"], baseline_category=prior["category"],
                         category=current["category"], baseline_proof=old_p, proof=new,
                         retained=compare_proofs(old_p, new)))
    assert len(data) == 65
    return data


def main(prefix, output, first_attempt):
    logs = Path("logs")
    old = read(HERE.parent / "m1-nosl3c-iii9a/evidence.json")
    identity, _, _ = ledger(logs / f"{prefix}-pair16/training.sqlite")
    engine = identity["engine"]
    history = frozen(prefix, old, engine)
    original = {(r["ledger"], r["step"], r["root"]): r for r in old["resampled"]}
    samples = []
    for group, witnesses in A["GROUPS"].items():
        folder = logs / f"{prefix}-sample-{group}"
        identity, batch = A["sample"](folder)
        assert identity["engine"] == engine and read(folder / "report.json")["optimizer"] == {}
        for key, current in zip(witnesses, batch, strict=True):
            previous = original[key]
            baseline = previous["observed"]
            assert identity["config"] == previous["config_sha256"]
            assert all(current[field] == baseline[field] for field in ("spec", "root_sha256", "behavior"))
            changes = next((i for i, (a, b) in enumerate(zip(baseline["decisions"], current["decisions"]))
                            if a != b), None)
            if changes is None and len(baseline["decisions"]) != len(current["decisions"]):
                changes = min(len(baseline["decisions"]), len(current["decisions"]))
            samples.append(dict(ledger=key[0], step=key[1], root=key[2], source_group=group,
                                budget=previous["budget"], config_sha256=identity["config"],
                                baseline=baseline, observed=current, first_decision_change=changes,
                                retained=compare_proofs(baseline["audit"], current["audit"])))
    prefix_data = read(logs / f"{prefix}-prefix/prefix.json")
    risks = read(logs / f"{prefix}-risks/risks.json")
    assert prefix_data["engine"] == risks["engine"] == engine
    pair = suite(prefix, "pair16", 16, engine)
    holdout = suite(prefix, "holdout", 60, engine)
    training = B["training"](prefix, engine)
    # Timing fields are intentionally outside the existing semantic-row projection.
    root_hashes = {}
    for mode in ("cold", "resume"):
        _, _, rows = ledger(logs / f"{prefix}-{mode}/training.sqlite")
        root_bytes = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        root_hashes[mode] = sha256(root_bytes).hexdigest()
    training["semantic_rows_sha256"] = root_hashes
    tests = ET.parse(logs / f"{prefix}-main.xml").getroot()
    counts = Counter()
    skipped, failed, languages = [], [], []
    for case in tests.iter("testcase"):
        status = next((tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None), "passed")
        counts[status] += 1
        if case.attrib["classname"].endswith("TestLanguage"):
            languages.append(dict(test=case.attrib["name"], status=status))
        if status != "passed":
            item = dict(name=case.attrib["classname"] + "::" + case.attrib["name"],
                        detail=case.find(status).attrib.get("message"))
            (skipped if status == "skipped" else failed).append(item)
    metadata = [read(path) for path in sorted(logs.glob(f"{prefix}-*-time.json"))]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    result = dict(evidence_export_head=head, engine=engine, timings=metadata, build=read(logs / "iij4-solver/build.json"),
                  history=history, risk_prefixes=prefix_data["results"], risk_diagnostics=risks["results"],
                  resampled=samples, pair16=pair, holdout=holdout, training=training,
                  main_tests=dict(counts=counts, skipped=skipped, failed=failed, languages=languages,
                                  seconds=float(tests.find("testsuite").attrib["time"]),
                                  host=B["HOST"].as_posix(), host_sha256=B["digest"](B["HOST"]),
                                  log_sha256=B["digest"](logs / f"{prefix}-main-pytest.log")))
    retained = {name: sum(exact(row["baseline_proof"]) and row["retained"] for row in entries)
                for name, entries in (("history", history), ("pair16", pair["roots"]),
                                      ("holdout", holdout["roots"]))}
    witness_specs = (
        ("II-E", 1, "000002", "admissible_predicted_win", 43, 31),
        ("II-E", 1, "000003", "admissible_death", 66, 58),
        ("pair16", 0, "000004", "admissible_predicted_win", 37, 33),
        ("holdout", 0, "000020", "admissible_death", 10, 8),
        ("holdout", 1, "000005", "admissible_death", 32, 26),
    )
    witness_checks = []
    for group, step, root, status, decisions, boundaries in witness_specs:
        if group == "II-E":
            row = next(r["observed"] for r in samples
                       if (r["ledger"], r["step"], r["root"]) == (group, step, root))
            actual, count = row["audit"], len(row["decisions"])
        else:
            row = next(r for r in result[group]["roots"] if (r["step"], r["root"]) == (step, root))
            actual, count = row["proof"], row["decisions"]
        witness_checks.append(dict(group=group, step=step, root=root,
            passed=exact(actual) and (actual["status"], count, actual.get("boundaries")) ==
            (status, decisions, boundaries)))
    comparison = training["comparison"]
    risk_statuses = Counter(r["observed"]["audit"]["status"] for r in samples)
    gates = dict(
        retained=retained == {"history": 42, "pair16": 11, "holdout": 50},
        witnesses=all(row["passed"] for row in witness_checks),
        risk_prefixes=len(prefix_data["results"]) == len(risks["results"]) == 8 and all(
            row["status"] == "active" and len(row["steps"]) == row["archived_actions"] and
            all(step.get("stamp") for step in row["steps"]) for row in prefix_data["results"]) and all(
            len(row["before"]) == len(row["after"]) and any(f["risk"] for f in row["before"]) and
            not any(f["risk"] for f in row["after"]) for row in risks["results"]),
        risk_resamples=all(r["retained"] and exact(r["observed"]["audit"]) for r in samples)
            and risk_statuses == {"admissible_predicted_win": 3, "admissible_death": 5},
        training=(comparison["roots"], comparison["snapshots"]) == (32, 3) and all(
            comparison[k] for k in ("identity_equal", "snapshots_equal", "semantic_rows_equal"))
            and root_hashes["cold"] == root_hashes["resume"],
        main_tests=counts == {"passed": 164, "skipped": 1} and {
            item["test"] for item in languages if item["status"] == "passed"} == {
                "test_lang_en_returns_english", "test_lang_zh_returns_chinese", "test_default_lang_is_english"},
    )
    result["gates"] = gates
    result["retained_strict"] = retained
    result["witness_checks"] = witness_checks
    result["final_model_sha256"] = training["snapshots"][-1]["stats"].get("model_sha256")
    if first_attempt:
        names = ("archive", "prefix", "risks", "risks-run", "main-pytest")
        result["first_attempt"] = {
            name: dict(path=path.as_posix(), sha256=B["digest"](path),
                       tail=path.read_text(encoding="utf-8", errors="replace").splitlines()[-2:])
            for name in names if (path := logs / f"{first_attempt}-{name}.log").exists()
        }
        for name in ("pair16", "holdout", "sample-2"):
            directory = logs / f"{first_attempt}-{name}"
            _, _, roots = ledger(directory / "training.sqlite")
            result["first_attempt"][name] = dict(counts=Counter(r[3] for r in roots), failures=[
                dict(step=step, root=root, status=status, audit=proof(directory, step, root))
                for _, step, root, status, _, _ in roots
                if status in ("root_failure", "engine_failure", "audit_failure")])
    output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    for name, rows in (("history", history), ("pair16", pair["roots"]), ("holdout", holdout["roots"])):
        print(name, Counter(row["classification"] for row in rows),
              "retention failures", [row["root"] for row in rows if not row["retained"]])
    print("risk samples", Counter(row["observed"]["audit"]["status"] for row in samples))
    print("training", training["comparison"], "main tests", counts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix")
    parser.add_argument("output", type=Path)
    parser.add_argument("--first-attempt")
    args = parser.parse_args()
    main(args.prefix, args.output, args.first_attempt)
