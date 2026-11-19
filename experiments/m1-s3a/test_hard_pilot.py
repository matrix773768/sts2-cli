"""Check the frozen generator, version boundary, failures and resume evidence."""
from pathlib import Path

from generate import generate
from summarize import read

HERE = Path(__file__).resolve().parent


def test_new_generator_is_reproducible_and_only_materializes_development():
    plan = read(HERE / "plan.json")
    catalog = read(HERE / "catalog.json.gz")
    manifest = read(HERE / "pilot.json")
    assert generate(plan, catalog) == manifest
    cases = manifest["cases"]
    assert len(cases) == len({c["id"] for c in cases}) == 24
    assert all(c["spec"]["act"] == 2 and c["split"] == "development" for c in cases)
    assert sum(c["refine"] for c in cases) == 6


def test_fixed_and_frozen_aba_and_risk_scoping():
    old, new = [read(HERE / f"{name}-pair.json.gz")["rows"] for name in ("frozen", "fixed")]
    assert len(old) == len(new) == 7
    for rows in (old, new):
        assert len({r["pid"] for r in rows}) == 1
        assert rows[0]["semantic_sha256"] == rows[2]["semantic_sha256"]
        assert all(r["loaded_solver"]["sha256"] == r["solver_sha256"] for r in rows)
    assert old[0]["solver_sha256"] != new[0]["solver_sha256"]
    for before, after in zip(old, new, strict=True):
        assert before["root_sha256"] == after["root_sha256"]
        assert before["selected"]["hp"] == after["selected"]["hp"]
        assert before["selected"]["actions"] == after["selected"]["actions"]
        assert before["retirement"]["native_frames_sha256"] == after["retirement"]["native_frames_sha256"]
        assert not any(x.startswith("E3_PREDATOR") for x in after["risks"])
    assert sum(bool(r["retirement"]["prediction_stamp_mismatch_steps"]) for r in old) == 2
    assert not any(r["retirement"]["prediction_stamp_mismatch_steps"] for r in new)


def test_failures_recycle_and_smaller_budget_is_an_independent_run():
    hard = read(HERE / "hard.json.gz")["rows"]
    smaller = read(HERE / "budget128.json.gz")["rows"]
    assert len(hard) == 24 and all("root_sha256" in r for r in hard)
    assert sum(r["outcome"] == "predicted_win" for r in hard) == 3
    for row, next_row in zip(hard[:-1], hard[1:], strict=True):
        if row.get("discard_reason"):
            assert row["discard_exit_code"] != 0
            assert row["pid"] != next_row["pid"] and next_row["started_cold"]
    by_id = {row["input"]["id"]: row for row in hard}
    assert len(smaller) == 6
    for row in smaller:
        source = by_id[row["input"]["id"]]
        assert row["cap"] == 128 and source["cap"] == 512
        assert row["pid"] != source["pid"] and row["first"]["transitions"] <= 128
        assert row["root_sha256"] == source["root_sha256"]


def test_atomic_resume_does_not_replace_existing_records():
    data = read(HERE / "resume-proof.json")
    assert data["previous_record_hashes"] == data["after_resume_hashes"]
    assert (data["resumed_count"], data["new_count"], data["ordinals"]) == (2, 1, [1, 2, 3])
