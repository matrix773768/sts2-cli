"""Check the supported input boundary and measured worker lifecycle."""
import gzip
import json
from pathlib import Path

import pytest

from run_probe import validate

HERE = Path(__file__).resolve().parent


def evidence(name):
    with gzip.open(HERE / f"{name}.json.gz", "rt", encoding="utf-8") as stream:
        return json.load(stream)


def test_manifest_rejects_unimplemented_fields_and_known_adapter_conflict():
    data = json.loads((HERE / "inputs.json").read_text(encoding="utf-8"))
    for row in data["cases"]:
        validate(row["spec"])
    sample = data["cases"][0]["spec"]
    with pytest.raises(ValueError, match="schema-2"):
        validate(sample | {"gold": 500})
    with pytest.raises(ValueError, match="Neutralize"):
        validate(sample | {"deck": [{"id": "NEUTRALIZE", "upgrade": 0}]})


def test_pilot_and_long_resident_sequence_match_cold():
    for name, count in (("pilot", 3), ("sequence", 24)):
        data = evidence(name)
        resident, cold = data["resident"]["rows"], data["cold"]["rows"]
        assert len(resident) == len(cold) == count
        assert len({r["pid"] for r in resident}) == 1
        assert len({r["pid"] for r in cold}) == count
        for hot, ref in zip(resident, cold, strict=True):
            assert hot["input"] == ref["input"]
            assert hot["root_timing"]["handshake_ms"] == hot["handshake_ms"]
            if hot["ordinal"] > 1:
                assert hot["handshake_ms"] == 0
            assert hot["matched_control"] and hot["semantic_sha256"] == ref["semantic_sha256"]
            assert hot["rng_sha256"] == ref["rng_sha256"]
            assert hot["synthetic"] and hot["natural_reachability"] == "unknown"
            assert hot["evidence_level"] == "prediction_only" and hot["outcome"] == "predicted_win"
            assert hot["first"]["transitions"] + hot["quality"]["transitions"] <= 512
            assert hot["selected"]["potions"] == hot["first"]["winner"]["potions"]
            assert not hot.get("discard_reason")
            if hot["selected"]["actions"][-1]["card_id"] == "PREDATOR":
                assert "E3_PREDATOR_TERMINAL" in hot["risks"]


def test_live_reset_cancel_and_timeout_discard_workers():
    faults = evidence("faults")["faults"]
    assert set(faults) == {"active_reset", "cancel", "timeout"}
    assert all(row["exit_code"] != 0 and row["exit_code"] is not None for row in faults.values())
    assert faults["cancel"]["failure"]["error_type"] == "EngineCancelled"
    assert faults["timeout"]["failure"]["status"] == "timeout"
