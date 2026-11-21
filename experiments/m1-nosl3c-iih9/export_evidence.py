"""Export a read-only II-H.9 comparison against the established full baseline."""
import argparse
from contextlib import closing
import gzip
from collections import Counter
import json
import re
from hashlib import sha256
from pathlib import Path
import runpy
import sqlite3

HERE = Path(__file__).resolve().parent
journal = runpy.run_path(str(HERE.parent / "m1-nosl3c-iih3-stabilization/compare_journals.py"))


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def replay_rows(folder, ledger):
    return {(row["step"], row["position"]): row
            for row in read(folder / f"{ledger}.json")}


def proof_fields(proof):
    fields = ("status", "certification", "exact_status", "reason", "first_failure",
              "continuation_fields", "detail", "terminal_verified", "native_terminal_stamp")
    return {field: proof[field] for field in fields if field in proof}


def history(logs):
    baseline, current = (logs / f"{name}-archive" for name in ("iih3-stable", "iih9"))
    ledgers = read(current / "summary.json")["ledgers"]
    output = []
    for ledger in ledgers:
        old, new = replay_rows(baseline, ledger), replay_rows(current, ledger)
        assert old.keys() == new.keys()
        for key, after in new.items():
            before = old[key]
            assert before["root"] == after["root"]
            output.append(dict(ledger=ledger, step=key[0], position=key[1],
                               root=after["root"], baseline=before["native_classification"],
                               category=after["category"], classification=after["native_classification"],
                               archived=after["archived_actions"], consumed=after.get("consumed_decisions", 0),
                               last_card=(after.get("last_submitted") or {}).get("card"),
                               proof=proof_fields(after.get("result", {})),
                               differing_fields=after.get("result", {}).get("fields"),
                               divergence_index=after.get("result", {}).get("position")))
    assert len(output) == 65
    return output


def first_changes(before, after):
    changes = {}
    for index, (old, new) in enumerate(zip(before, after)):
        for field in ("observation", "action", "behavior_logp"):
            if field in changes or old[field] == new[field]:
                continue
            first, second = old[field], new[field]
            if field == "observation":
                keys = sorted(k for k in first.keys() | second.keys() if first.get(k) != second.get(k))
                changes[field] = dict(index=index, fields=keys)
            else:
                changes[field] = dict(index=index, old=first, new=second)
    if len(before) != len(after):
        changes["trajectory_length"] = [len(before), len(after)]
    return changes


def paired(logs, suite, denominator):
    baseline, current = (logs / f"{name}-{suite}" for name in ("iih3-stable", "iih9"))
    old, new = (journal["read"](folder / "training.sqlite")[2] for folder in (baseline, current))
    assert len(old) == len(new) == denominator
    rows = []
    for (phase, step, root, old_status, spec, before), actual in zip(old, new, strict=True):
        assert (phase, step, root, spec) == (*actual[:3], actual[4])
        new_status, after = actual[3], actual[5]
        proofs = []
        for folder in (baseline, current):
            audit = folder / "audit" / f"{step:06d}-{root}.json"
            proofs.append(proof_fields(read(audit)) if audit.exists() else {})
        original = before[0] if before else {}
        observed = after[0] if after else {}
        rows.append(dict(step=step, position=root, encounter=spec["encounter"],
                         baseline=old_status, classification=new_status,
                         baseline_proof=proofs[0], proof=proofs[1],
                         baseline_prediction=original.get("feedback", {}).get("status"),
                         prediction=observed.get("feedback", {}).get("status"),
                         first_changes=first_changes(original.get("transitions", []),
                                                     observed.get("transitions", []))))
    return rows


def training(logs, engine):
    snapshots = {}
    admissions = []
    for run in ("cold", "resume"):
        path = (logs / f"iih9-{run}/training.sqlite").resolve()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        identity, states, roots = journal["read"](path)
        assert json.loads(identity)["engine"] == engine
        snapshots[run] = [dict(step=i, sha256=sha, stats=json.loads(gzip.decompress(stats)))
                          for i, sha, _, stats in states]
        assert len(roots) == 32 and [state[0] for state in states] == [0, 1, 2]
        if run == "cold":
            for phase, step, root, status, spec, rows in roots:
                eligible = [row for row in rows if row["feedback"]["eligible"]]
                assert all(row["qualification"]["mode"] == "exact"
                           and row["qualification"]["certification"] == "exact_native_match"
                           for row in eligible)
                admissions.append(dict(phase=phase, step=step, position=root,
                                       encounter=spec["encounter"], classification=status,
                                       eligible=len(eligible),
                                       qualification=[row["qualification"] for row in rows]))
    comparison = read(logs / "iih9-journals.json")
    return dict(comparison=comparison, snapshots=snapshots, admissions=admissions)


def native_fixtures(logs, engine):
    paths = dict(shadow="fixture-shadow/nonlethal.json", gas="fixture-gas/lifecycle.json",
                 death="fixture-death/lifecycle.json", legality="legality/legality.json",
                 forge="forge/forge.json", blade="blade/history.json")
    outcomes = {name: read(logs / ("iih9-" + path)) for name, path in paths.items()}
    for outcome in outcomes.values():
        assert outcome.pop("engine") == engine
    return outcomes


def main_tests(logs):
    output = (logs / "iih9-main-pytest.log").read_text(encoding="utf-8")
    failures = re.findall(r"^FAILED (\S+)", output, re.MULTILINE)
    summary = next(line for line in reversed(output.splitlines()) if " passed" in line)
    host = logs / "iih9-main-host/Sts2Headless.dll"
    return dict(summary=summary, failures=failures, classification="environment_failure",
                first_failure="Offering lookup raised StopIteration after reaching the boss reward",
                detail="Output path depth bypassed repository localization directories",
                headless_sha256=sha256(host.read_bytes()).hexdigest())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--logs", type=Path, default=Path("logs"))
    args = parser.parse_args()
    logs = args.logs
    facts = dict(engine=read(logs / "iih9-archive/summary.json")["versions"],
                 history=history(logs), pair16=paired(logs, "pair16", 16),
                 holdout=paired(logs, "holdout", 60))
    facts["training"] = training(logs, facts["engine"])
    facts["native_fixtures"] = native_fixtures(logs, facts["engine"])
    facts["main_tests"] = main_tests(logs)
    args.output.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name in ("history", "pair16", "holdout"):
        print(name, dict(Counter(row["classification"] for row in facts[name])))
