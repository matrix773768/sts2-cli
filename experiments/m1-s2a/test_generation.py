"""Native S2A experiment acceptance and fail-closed model checks."""
from copy import deepcopy
import os
from pathlib import Path

import pytest

import generate as gen

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ.get("STS2_S2A_RESULTS", HERE.parents[1] / "logs/m1-s2a/formal"))


def test_generation_seeds_and_dedup():
    plan = gen.bank.read(HERE / "plan.json")
    catalog = gen.bank.read(WORK / "catalog.json")
    cohort = gen.bank.read(WORK / "cohort.json")
    fresh = gen.generate(plan, catalog)
    assert fresh == cohort["cases"]
    assert len(fresh) == 16 and len({c["spec"]["seed"] for c in fresh}) == 16
    assert {c["rule"] for c in fresh} == {"strength", "block", "poison", "shiv"}
    assert {c["spec"]["act_variant"] for c in fresh} == {"OVERGROWTH", "UNDERDOCKS", "HIVE"}
    assert len({c["spec"]["hp"] for c in fresh}) > 4
    assert gen.deduplicate(fresh + fresh[:2], "spec_sha256") == (fresh, [c["case"] for c in fresh[:2]])
    wrong = deepcopy(plan)
    wrong["rules"]["strength"]["attack"] = ["DAGGER_SPRAY"]
    with pytest.raises(ValueError, match="incompatible native card"):
        gen.generate(wrong, catalog)


def test_native_roots_and_f3b_subset():
    dataset = gen.bank.read(WORK / "records.json")
    rows = dataset["cases"]
    assert len(rows) == 16 and not dataset["failures"]
    assert len({r["live"] for r in rows}) == 16
    assert len(dataset["repeated_cases"]) == 4 and dataset["native_save_or_replay_files"] == 0
    assert {r["case"] for r in rows if r["f3b"]} == set(dataset["f3b_selection"])
    catalog = gen.bank.read(WORK / "catalog.json")
    for row in rows:
        root, spec = row["root"], row["spec"]
        assert root["native_verified"] and root["native_reachable"] == "unknown"
        assert root["synthetic"] and root["native"]["visited_map_nodes"] == 0
        assert len(row["audit"]["rebuilds"]) == 2
        assert root["native"]["deck"] == spec["deck"]
        assert root["public_root"]["context"]["act"] == spec["act"]
        assert root["native"]["act_variant"] == spec["act_variant"]
        variant = next(a for a in catalog["acts"] if a["variant"] == spec["act_variant"])
        assert {"id": root["native"]["act_boss"], "room": "Boss"} in variant["encounters"]
        if root["level"] == "L3":
            replay = row["f3b"]["native_replay"]
            assert replay["strict_terminal"] and replay["matched_actions"] == len(row["f3b"]["actions"])
            assert all(s["actual_sha256"] == s["expected_sha256"] for s in replay["trace"])
    assert any(r["root"]["level"] == "L3" for r in rows)


def test_native_rejects_incompatible_variant_encounter_and_card(tmp_path):
    case = gen.bank.read(WORK / "cohort.json")["cases"][0]["spec"]
    gen.bank.versions_for_host(tmp_path, gen.HOST)
    with gen.synth.new_session(tmp_path) as game:
        for override, reason in (
            ({"act": 2, "act_variant": "UNDERDOCKS"}, "Unknown act variant"),
            ({"encounter": "TUNNELER_WEAK"}, "ordinary member"),
            ({"deck": [{"id": "STRIKE_SILENT", "upgrade": 0}]}, "outside the native character pool"),
            ({"relics": ["RING_OF_THE_SNAKE"]}, "Unsupported synthetic relic or potion"),
            ({"potions": ["FIRE_POTION"]}, "Unsupported synthetic relic or potion"),
        ):
            reply = game.engine.send({"cmd": "synthetic_start", "spec": case | override})
            assert reply["type"] == "error" and reason in reply["message"]
