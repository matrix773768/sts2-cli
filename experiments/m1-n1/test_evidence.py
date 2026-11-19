from collections import Counter
import hashlib
import json

from test_baseline import HERE
from summarize import read


def test_target_experiment_pairs_with_frozen_engine():
    baseline = HERE / "baseline.jsonl.gz"
    digest = hashlib.sha256(baseline.read_bytes()).hexdigest()
    controls = {r["case"]["id"]: r for r in read(baseline)
                if r["cohort"] == "S3B" and r["result"]["strategy"] == "ENGINE"
                and r["case"]["spec"]["encounter"] == "BOWLBUGS_NORMAL"}
    rows = read(HERE / "target-experiment.jsonl.gz")
    assert len(controls) == 24
    assert Counter(r["result"]["strategy"] for r in rows) == {"THREAT_V1": 24, "DURABLE_V1": 1}
    for row in rows:
        control = controls[row["case"]["id"]]
        assert row["baseline_sha256"] == digest
        assert row["root_sha256"] == control["root_sha256"]
        assert row["result"]["start"]["stamp"] == control["result"]["start"]["stamp"]


def test_public_and_native_evidence_are_independent():
    public = json.loads((HERE / "public-target.json").read_text(encoding="utf-8"))["rows"]
    assert Counter(r["policy"] for r in public) == {"PUBLIC_SCORE_V1": 4, "PUBLIC_THREAT_V1": 4}
    assert all(r["status"] == "death" for r in public)
    representative = [r for r in public if r["id"] == "f2f29fd990637955"]
    assert representative[0]["actions"][4]["action"] != representative[1]["actions"][4]["action"]
    audits = json.loads((HERE / "native-audit.json").read_text(encoding="utf-8"))
    assert [(r["check"]["status"], r["check"]["matched_actions"]) for r in audits] == [
        ("win", 12), ("win", 20), ("win", 37)]
