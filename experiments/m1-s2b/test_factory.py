"""Check frozen S2B planning, interrupted collection and independent route evidence."""
from collections import Counter
import hashlib
import os
from pathlib import Path

import pytest

import factory as s2b

HERE = Path(__file__).resolve().parent
OUTPUT = Path(os.environ.get("STS2_S2B_RESULTS", HERE.parents[1] / "logs/m1-s2b"))


def test_plan_reproducibility_and_encounter_holdout():
    formal = s2b.prepare_plan(OUTPUT / "formal")
    pilot = s2b.prepare_plan(OUTPUT / "pilot")
    catalog = s2b.bank.read(HERE.parents[1] / "logs/m1-s2a/formal/catalog.json")
    assert formal == s2b.planned(formal["config"], "formal", 4, catalog, formal["versions"])
    assert pilot == s2b.planned(pilot["config"], "pilot", 1, catalog, pilot["versions"])
    assert len(formal["cases"]) == 256 and len(pilot["cases"]) == 32
    assert {c["spec"]["seed"] for c in formal["cases"]}.isdisjoint(c["spec"]["seed"] for c in pilot["cases"])
    assert len({c["spec_sha256"] for c in formal["cases"]}) == 256
    assert set(Counter(tuple(c["family"]) + (c["profile"],) for c in formal["cases"]).values()) == {2}
    by_split = {split: {c["spec"]["encounter"] for c in formal["cases"] if c["split"] == split}
                for split in s2b.SPLITS}
    assert [len(by_split[split]) for split in s2b.SPLITS] == [4, 2, 2]
    assert len(set.union(*by_split.values())) == sum(map(len, by_split.values()))
    selected = set(formal["evaluation_ids"])
    assert Counter(c["split"] for c in formal["cases"] if c["id"] in selected) == {"development": 2, "test": 2}


def test_append_is_prefix_only(tmp_path):
    catalog = s2b.bank.read(HERE.parents[1] / "logs/m1-s2a/formal/catalog.json")
    config = s2b.bank.read(HERE / "config.json")
    small = s2b.planned(config, "pilot", 1, catalog, {})
    more = s2b.planned(config, "pilot", 2, catalog, {})
    path = tmp_path / "plan.json"
    s2b.pinned(path, small, False)
    with pytest.raises(ValueError, match="Frozen plan differs"):
        s2b.pinned(path, more, False)
    s2b.pinned(path, more, True)
    assert s2b.bank.read(path) == more
    assert more["cases"][:32] == small["cases"] and more["evaluation_ids"] == small["evaluation_ids"]


def test_resume_did_not_replace_committed_artifacts():
    pilot = OUTPUT / "pilot"
    if not (pilot / "resume-prefix.json").exists():
        pytest.skip("No deliberate interruption fixture in this reproduction")
    original = s2b.bank.read(pilot / "resume-prefix.json")
    assert 0 < len(original) < 32
    assert all(hashlib.sha256((pilot / "roots" / filename).read_bytes()).hexdigest() == digest
               for filename, digest in original.items())
    assert s2b.bank.read(pilot / "batches.json")[-2]["stop"] == "batch_timeout"
    assert s2b.bank.read(pilot / "batches.json")[-1]["stop"] == "complete"


@pytest.mark.parametrize(("cohort", "size"), [("pilot", 32), ("formal", 256)])
def test_native_artifacts_and_audit(cohort, size):
    output = OUTPUT / cohort
    plan = s2b.prepare_plan(output)
    records = s2b.records(output, plan)
    s2b.validate_ownership(plan, records)
    assert len(records) == size
    index = s2b.summary(plan, records)
    assert index == s2b.bank.read(output / "index.json")
    assert index["status_counts"] == {"verified": size}
    assert not s2b.native_files(output)
    assert len({v["root"]["identity"]["live"] for v in records.values()}) == size
    for row in records.values():
        native = row["root"]["native"]
        assert native["should_save"] is False and native["replay_writer_enabled"] is False
        assert native["visited_map_nodes"] == 0
        assert len(row["audit"]["rebuilds"]) == 2
    labels = s2b.verify_labels(output, plan, records)
    assert {(label["case_id"], label["policy"]) for label in labels.values()} == {
        (case_id, policy) for case_id in plan["evaluation_ids"] for policy in ("f3b", "f4")}
    assert all(label["cap"] == plan["config"]["evaluation"]["budget"] for label in labels.values())


def test_fixed_replay_shares_budget_with_retry(monkeypatch, tmp_path):
    tries, replays = [], []
    search, validation = iter((50, 48)), iter(("prediction_mismatch",))

    def predict(output, root, arm, potions, cap, rejected, restore):
        tries.append((cap, list(rejected)))
        return dict(status="predicted_win", transitions=next(search),
                    actions=[{}] * 20, winner_key=str(len(tries)))

    def verify(output, root, result, restore, keep_frames):
        replays.append(result["winner_key"])
        return dict(status=next(validation))

    monkeypatch.setattr(s2b.f3b, "search", predict)
    monkeypatch.setattr(s2b.f3b, "expect_native", verify)
    control = s2b.f3b.run_cell(tmp_path, {"id": "case", "identity": {"encounter": "check"}},
                              "C", False, 128, charge_fixed=True)
    assert tries == [(128, []), (58, ["1"])]
    assert replays == ["1"]
    assert control["status"] == "prediction_only_budget" and control["total_charged"] == 118
    assert s2b.proof_level(s2b.quality.history(tmp_path / control["history"])) == "L2"
