"""Check split sealing, quantification and reproducibility of the S2C benchmark."""
from collections import Counter
import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("s2c_benchmark", HERE / "benchmark.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
BANK = ROOT / "logs/m1-s2b/formal"
RUN = ROOT / "logs/m1-s2c"
FORMAL = Path(os.environ.get("STS2_S2C_FORMAL", RUN / "formal-v2"))
PILOT = Path(os.environ.get("STS2_S2C_PILOT", RUN / "pilot"))


def test_stratification_and_test_exclusion(monkeypatch):
    index = bench.bank.read(bench.INDEX)
    frozen = bench.bank.read(bench.SELECTION)
    assert bench.freeze(index) == frozen
    rows = frozen["selection"]
    assert Counter(row["split"] for row in rows) == {"development": 32, "validation": 16}
    assert set(Counter((r["split"], r["encounter"], r["rule"]) for r in rows).values()) == {1}
    assert {r["id"] for r in rows}.isdisjoint(index["evaluation_ids"])
    opened = []
    checked = bench.s2b.checked

    def watch(path):
        opened.append(path.name.removesuffix(".json.gz"))
        return checked(path)

    monkeypatch.setattr(bench.s2b, "checked", watch)
    _, selected = bench.inputs(BANK, frozen, "all")
    assert set(opened) == set(selected) == {r["id"] for r in rows}
    withheld = next(r for r in index["rows"] if r["split"] == "test")
    modified = frozen | {"selection": rows + [{k: withheld[k] for k in bench.FIELDS}]}
    with pytest.raises(ValueError, match="distinct verified development/validation"):
        bench.inputs(BANK, modified, "all")


def test_failure_categories_and_first_different_fields():
    raw = [{"exact_continuation_state": "Y=0/1/2/2;FlameHp=6;AttackStarts=1"}]
    actual = [{"exact_continuation_state": "Y=0/1/0/0;FlameHp=6;AttackStarts=0"}]
    audit = bench.audit_trial({"status": "predicted_win", "verification": {
        "status": "prediction_mismatch", "matched_actions": 9, "trace": [{"native_action": "EndTurn"}],
        "first_difference": {"phase": 10, "expected": raw, "actual": actual}}})
    assert audit["first_step"] == 10 and audit["category"] == "simulator_difference"
    assert {field["field"].split(".")[-1] for field in audit["fields"]} == {"Y", "AttackStarts"}
    other = bench.audit_trial({"status": "predicted_win", "verification": {
        "status": "independent_prediction_rejected", "preparation": {"status": "engine_error"}}})
    assert other["category"] == "execution_correctness" and other["phase"] == "fixed_prediction"
    assert bench.audit_trial({"status": "transition_cap"})["category"] == "resource_exhaustion"
    assert bench.audit_trial({"status": "candidates_exhausted"})["category"] == "search_coverage"
    assert bench.wilson(16, 16) == [0.8064, 1]


def test_completed_pairs_and_pilot_reproducibility():
    formal = bench.bank.read(FORMAL / "report.json")
    pilot = bench.bank.read(PILOT / "report.json")
    assert formal["complete_cells"] == formal["expected_cells"] == 96
    assert formal["test_evaluated"] == 0
    ids = {row["id"]: row for row in formal["rows"]}
    for previous in pilot["rows"]:
        current = ids[previous["id"]]
        for policy in bench.POLICY:
            # Timings, process IDs and paths are deliberately absent from the signature.
            fields = ("level", "status", "first_prediction", "first_strict", "total_charged", "selected")
            assert {k: previous[policy][k] for k in fields} == {k: current[policy][k] for k in fields}
    for row in formal["rows"]:
        for policy in bench.POLICY:
            cell = row[policy]
            assert cell["total_charged"] <= 512
            if cell["level"] == "L3":
                assert cell["first_strict"] <= cell["total_charged"]
            else:
                assert cell["selected"] is None and cell["first_strict"] is None
    diagnosis = bench.bank.read(FORMAL / "audit.json")
    assert diagnosis["cases"] == diagnosis["expected"]
    assert diagnosis["unresolved"] == diagnosis["expected_unresolved"] == sum(
        r["f3b"]["level"] != "L3" for r in formal["rows"])


def test_resume_kept_existing_label_bytes():
    path = FORMAL / "resume-prefix.json"
    if not path.exists():
        pytest.skip("No interruption fixture in this run")
    prefix = bench.bank.read(path)
    assert 0 < len(prefix) < 96
    for filename, digest in prefix.items():
        assert hashlib.sha256((FORMAL / "labels" / filename).read_bytes()).hexdigest() == digest
    runs = bench.bank.read(FORMAL / "sessions.json")
    assert (runs[0]["stop"], runs[-1]["stop"]) == ("batch_timeout", "complete")


def test_parallel_native_file_scan_ignores_only_removed_directories(monkeypatch, tmp_path):
    def disappearing(path, onerror):
        onerror(FileNotFoundError("worker removed its profile"))
        yield path, [], ["fixture.mcr", "stdout.log"]

    monkeypatch.setattr(bench.s2b.os, "walk", disappearing)
    assert bench.s2b.native_files(tmp_path) == ["fixture.mcr"]

    def inaccessible(path, onerror):
        onerror(PermissionError("profile inaccessible"))

    monkeypatch.setattr(bench.s2b.os, "walk", inaccessible)
    with pytest.raises(PermissionError, match="profile inaccessible"):
        bench.s2b.native_files(tmp_path)
