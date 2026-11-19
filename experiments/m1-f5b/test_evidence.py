"""Regression checks for the recorded paired runs and strict-native controls."""
from pathlib import Path

from summarize import MODES, read, summarize, total

HERE = Path(__file__).resolve().parent


def test_prediction_pairs_preserve_budget_and_incumbent():
    development, validation = (read(HERE / f"{split}.json.gz")["rows"]
                               for split in ("development", "validation"))
    protocol = read(HERE / "protocol.json")
    assert len(development) == 20 and len(validation) == 8
    assert {row["case"]["id"]: row["stress_hp"] for row in development if row["stress_hp"]} == (
        protocol["stress_development"])
    assert all(row["case"]["split"] == "validation" and row["stress_hp"] is None for row in validation)
    for row in development + validation:
        assert "fault" not in row
        for mode, source in MODES.items():
            assert 0 <= total(row, mode, "transitions") <= 512
            first = row["first"][source].get("winner")
            final = row["pareto"][mode]["512"]
            if first:
                assert final["hp"] >= first["hp"] and final["potions"] == first["potions"]
            else:
                assert final is None and row["refine"][mode] is None
    assert summarize(validation)["hp_delta"]["512"]["same_seed"] == {"equal": 5, "worse": 3}


def test_frozen_host_parity_and_predator_mismatch_remain_visible():
    rows = read(HERE / "audit.json.gz")["rows"]
    assert len(rows) == 2 and all(row["baseline"] == [[], []] for row in rows)
    checked = [r for row in rows for r in row["native_controls"]]
    assert any(r["evidence"]["strict_terminal"] for r in checked)
    assert any(r["predator_terminal"] and r["evidence"]["status"] == "prediction_mismatch"
               for r in checked)
