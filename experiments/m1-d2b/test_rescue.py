"""Acceptance checks for the small D2B native experiment and its fail-closed gate."""
import copy
import os
import random
from pathlib import Path
from threading import Event
from time import monotonic

import pytest

import rescue

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("STS2_D2B_RESULTS", ROOT / "logs/m1-d2b"))
SOURCE = Path(os.environ.get("STS2_D2B_SOURCE", ROOT / "logs/m1-d1-v1-w2"))
D2A = Path(os.environ.get("STS2_D2B_D2A_SOURCE", ROOT / "logs/m1-d2a/reruns"))


def artifact(directory):
    path = WORK / directory
    return path, rescue.bank.read(path / "rescue.json"), rescue.bank.read(path / "manifest.json")


@pytest.mark.parametrize("status", ("run_victory", "unsupported", "timeout", "execution_fault"))
def test_gate_rejects_non_death(status):
    manifest = {"runs": [{"id": "case", "status": status}]}
    with pytest.raises(ValueError, match="native death"):
        rescue.terminal_root(manifest, "case")


def test_q1_requires_matching_terminal_trace():
    death = {"status": "death", "root_verified": True, "outcome": {"final_hp": 0}}
    trace = [{"round": 3, "action": {"action": "end_turn"}, "choice_requests": [], "choice_checks": []}]
    resolved = {k: v for k, v in trace[0].items() if k != "round"}
    assert rescue.same_failure(death, trace, [{"resolved": resolved}])
    assert not rescue.same_failure(death | {"status": "win"}, trace, [{"resolved": resolved}])
    assert not rescue.same_failure(death | {"outcome": {"final_hp": 1}}, trace, [{"resolved": resolved}])
    assert not rescue.same_failure(death, trace, [{"resolved": {}}])


def test_success_rewalk_and_next_strict_root(tmp_path):
    output, row, bank = artifact("iron-6-a2")
    source = rescue.bank.read(SOURCE / "manifest.json")
    original, failed, _, suffix = rescue.terminal_root(source, "iron-6-a2")
    assert row["q1_matches_original"] and row["origin_result"] == "death"
    assert row["status"] == "native_continuation"
    assert row["known_transitions"] == row["charged_transitions"] == 10
    attempt, = row["attempts"]
    assert not attempt["potions"]
    assert row["applied"]["matched_actions"] == row["verified"]["matched_actions"] == 7
    proof = rescue.outcome_evidence(row["verified"])
    assert rescue.outcome_evidence(row["applied"]) == proof
    altered = copy.deepcopy(row["applied"])
    altered["native_final"]["resources"]["gold"] += 1
    assert rescue.outcome_evidence(altered) != proof
    assert row["applied"]["terminal_public"]["decision"] == "card_reward"
    q1, = bank["evaluations"]
    native_trace = next(r for r in bank["routes"] if r["kind"] == "native_policy_trace")
    assert rescue.same_failure(q1, native_trace["actions"], suffix)
    original_copy, branch = bank["runs"]
    assert original_copy == original and original_copy["status"] == "death"
    assert branch["parent"] == {"run_id": original["id"], "root_id": failed["id"],
                                "prefix_length": failed["entry_command_index"] - 1}
    assert branch["offline_teacher_assisted"]
    assert (branch["history"], branch["partition"]) == (original["history"], original["partition"])
    assert branch["commands"][0] == {"cmd": "action", **failed["entry"]}
    assert [c["cmd"] for c in branch["commands"][1:8]] == ["i1_step"] * 7
    assert branch["commands"][8]["action"] == "select_card_reward"
    next_roots = [r for r in bank["roots"] if r["id"] in row["new_strict_roots"]]
    assert [(r["context"]["act"], r["context"]["floor"], r["identity"]["encounter"]) for r in next_roots] == [
        (1, 13, "VINE_SHAMBLER_NORMAL"), (1, 14, "SNAPPING_JAXFRUIT_NORMAL")]
    assert all(r["offline_teacher_assisted"] for r in next_roots)
    assert (SOURCE / failed["checkpoint"]).read_bytes() == (output / failed["checkpoint"]).read_bytes()
    assert rescue.bank.versions_for_host(tmp_path, "m1-f3b-build") == bank["versions"]
    assert rescue.bank.audit(output, next_roots[-1], monotonic() + 15, Event())["status"] == "pass"


def test_exhausted_d2a_keeps_original_death():
    output, row, bank = artifact("iron-4")
    assert row["q1_matches_original"]
    assert row["status"] == "no_verified_win"
    assert [(a["potions"], a["status"], a["transitions"]) for a in row["attempts"]] == [
        (False, "exhausted", 65), (True, "exhausted", 65)]
    assert row["known_transitions"] == row["charged_transitions"] == 130
    assert "applied" not in row and "branch_run" not in row
    run, = bank["runs"]
    root, = bank["roots"]
    assert run["status"] == "death" and not run["offline_teacher_assisted"]
    assert (D2A / root["checkpoint"]).read_bytes() == (output / root["checkpoint"]).read_bytes()

def test_unsupported_search_does_not_apply_or_undercharge():
    _, row, bank = artifact("silent-8")
    assert row["q1_matches_original"] and row["status"] == "no_verified_win"
    assert [(a["potions"], a["status"], a["transitions"], a["charged_transitions"])
            for a in row["attempts"]] == [(False, "unsupported", None, 128), (True, "unsupported", None, 128)]
    assert row["known_transitions"] == 0 and row["charged_transitions"] == 256
    assert "applied" not in row and len(bank["runs"]) == 1


def test_archived_potion_and_choice_replay_remains_live(tmp_path):
    bank = rescue.bank
    f3a = rescue.f3a
    original = bank.read(SOURCE / "manifest.json")
    root = next(r for r in original["roots"] if r["run_id"] == "archive-east"
                and r["context"]["floor"] == 6)
    stage = ROOT / "experiments/m1-f3a/offline-reference-routes.json"
    ref = bank.read(stage)["run1-offering-east-a2f06"]
    assert bank.versions_for_host(tmp_path, "m1-f3b-build") == original["versions"]
    _, payload = bank.checkpoint_bytes(SOURCE, root)
    (tmp_path / root["checkpoint"]).write_bytes(payload)
    prep, plan = f3a.search(tmp_path, root, f3a.BUDGETS[0], ref["plan_actions"])
    assert prep["status"] == "complete_win"
    with bank.restore(tmp_path, root, monotonic() + 20, Event()) as (game, state):
        row = {}
        state = f3a.replay_live(game, state, plan, row)
        assert row["status"] == "win" and row["matched_actions"] == 17
        assert row["choice_evidence"]
        archived = ref["verification"]
        assert [s["actual_sha256"] for s in row["trace"]] == [s["actual_sha256"] for s in archived["trace"]]
        assert row["native_final"]["resources"] == archived["native_final"]["resources"]
        delta = bank.resource_delta(root["identity"]["resources"], row["native_final"]["resources"])
        assert len(delta["potion_slots"]) == 2
        spec = next(r["spec"] for r in original["runs"] if r["id"] == root["run_id"])
        assert state["decision"] == "card_reward"
        assert game.execute_action(bank.choose(state, spec, random.Random(0)))["decision"] == "map_select"
