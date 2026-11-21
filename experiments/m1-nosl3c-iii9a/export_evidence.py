"""Export the II-I.9A evidence from read-only archives and sample ledgers."""
from collections import Counter
from contextlib import closing
import gzip
import json
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
LOGS = Path("logs")
GROUPS = {
    1: (("II-E", 1, "000002"), ("II-C", 0, "000003")),
    2: (("II-D", 0, "000009"),),
    3: (("II-D", 0, "000025"),),
    4: (("II-D", 0, "000028"),),
    6: (("II-D", 0, "000027"),),
    7: (("II-E", 1, "000000"),),
    8: (("II-E", 1, "000003"),),
}


def read(path):
    return json.loads(path.read_bytes())


def history(archive):
    baseline = read(HERE.parent / "m1-nosl3c-iih9/evidence.json")["history"]
    summary = read(archive / "summary.json")
    current = {(ledger, row["step"], row["position"]): row
               for ledger in summary["ledgers"]
               for row in read(archive / f"{ledger}.json")}
    assert len(current) == len(baseline) == 65
    output = []
    for old in baseline:
        ledger, step, position = key = (old["ledger"], old["step"], old["position"])
        row = current[key]
        assert row["root"] == old["root"]
        proof = row.get("result", {})
        output.append(dict(
            ledger=ledger, step=step, position=position, root=row["root"],
            baseline=old["classification"], baseline_proof=old["proof"],
            classification=row["native_classification"], category=row["category"],
            archived=row["archived_actions"], consumed=row.get("consumed_decisions", 0),
            proof={field: proof[field] for field in (
                "status", "reason", "certification", "terminal_verified", "first_failure",
                "position", "fields", "detail", "continuation_fields", "native_terminal_stamp",
            ) if field in proof},
        ))
    certified = [row for row in output if row["baseline"] in ("certified_win", "certified_death")]
    assert len(certified) == 42
    for row in certified:
        assert row["classification"] == row["baseline"]
        assert row["proof"]["certification"] == "exact_native_match"
        assert row["proof"]["terminal_verified"]
        assert row["proof"]["native_terminal_stamp"] == row["baseline_proof"]["native_terminal_stamp"]
    return summary["versions"], output


def sample(folder):
    path = (folder / "training.sqlite").resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        identity = json.loads(db.execute("SELECT value FROM identity").fetchone()[0])
        roots = db.execute("SELECT step, root, rows FROM roots ORDER BY step, root").fetchall()
    result = []
    for step, root, blob in roots:
        item = json.loads(gzip.decompress(blob))
        row, = item["rows"]
        audit = read(folder / "audit" / f"{step:06d}-{root}.json")
        transitions = row["transitions"]
        decisions = []
        for transition in transitions:
            action = transition["action"]
            obs = transition["observation"]
            card = obs["hand"][action["card"]]["id"] if action["card"] is not None else None
            candidates = obs["decision"].get("candidates", [])
            choice = action.get("choice")
            candidate = candidates[choice]["id"] if choice is not None and candidates else None
            decisions.append(dict(kind=action["kind"], card=card, candidate=candidate,
                                  advanced=transition["advanced"]))
        deltas = {key: audit[key] for key in (
            "reason", "first_failure", "continuation_fields", "prediction_stop_detail",
        ) if key in audit}
        result.append(dict(spec=item["spec"], root_sha256=audit["root"], feedback=row["feedback"],
                           audit={key: audit.get(key) for key in (
                               "status", "certification", "boundaries", "terminal_verified", "route",
                               "native_terminal_stamp",
                           )} | deltas, behavior=row["behavior"], decisions=decisions))
    return identity, result


def paired(engine, run_prefix):
    result = []
    for phase, cases in GROUPS.items():
        prior = LOGS / f"iii{phase}-resample"
        current = LOGS / f"{run_prefix}-sample-{phase}"
        old_identity, old = sample(prior)
        new_identity, new = sample(current)
        assert new_identity["engine"] == engine
        assert {k: v for k, v in new_identity.items() if k != "engine"} == {
            k: v for k, v in old_identity.items() if k != "engine"}
        assert read(current / "report.json")["optimizer"] == {}
        for (ledger, step, root), before, after in zip(cases, old, new, strict=True):
            assert all(before[key] == after[key] for key in ("spec", "root_sha256", "behavior"))
            result.append(dict(ledger=ledger, step=step, root=root, budget=128,
                               config_sha256=new_identity["config"], prior_engine=old_identity["engine"],
                               prior=before, observed=after))
    return result


if __name__ == "__main__":
    engine, frozen = history(Path(sys.argv[1]))
    run_prefix = sys.argv[2] if len(sys.argv) > 2 else "iii9a"
    prefix = read(LOGS / f"{run_prefix}-prefix/prefix.json")
    risks = read(LOGS / f"{run_prefix}-risks/risks.json")
    assert prefix["engine"] == risks["engine"] == engine
    assert len(prefix["results"]) == len(risks["results"]) == 8
    for row in prefix["results"]:
        assert row["status"] == "active"
        assert len(row["steps"]) == row["archived_actions"]
        assert all(step.get("stamp") for step in row["steps"])
    for row in risks["results"]:
        assert len(row["before"]) == len(row["after"])
        assert any(frame["risk"] for frame in row["before"])
        assert not any(frame["risk"] for frame in row["after"])
    samples = paired(engine, run_prefix)
    intermediate = read(HERE.parent / "m1-nosl3c-iii5/evidence.json")["resampled"]
    evidence = dict(engine=engine,
                    build=read(LOGS / "m1-nosl3c-iii8-candidate/build.json"),
                    history=frozen, risk_prefixes=prefix["results"],
                    risk_diagnostics=risks["results"], resampled=samples,
                    intermediate_iii5=intermediate)
    (HERE / "evidence.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("history", Counter(row["classification"] for row in frozen))
    print("samples", Counter(row["observed"]["audit"]["status"] for row in samples))
