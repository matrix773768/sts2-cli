"""Negative controls for the versioned E3 admission boundary."""
from copy import deepcopy

import pytest

from certification import GAME, REASON, RULE, SOLVER, candidate, certify, completion


def row():
    return dict(transitions=[dict(action={"kind": "end_turn"})],
                feedback=dict(status="rule_risk", reason=REASON, actions=1,
                              eligible=False, observation={"hp": 4}))


def versions():
    return dict(solver_sha256=SOLVER, game_sha256=GAME, coreclr="9.0.7")


@pytest.mark.parametrize(("field", "value"), [("reason", "other"), ("eligible", True),
                                              ("status", "predicted_win"), ("actions", 2)])
def test_candidate_requires_original_quarantine(field, value):
    data = row()
    data["feedback"][field] = value
    assert not candidate(data)


def test_non_end_turn_is_not_candidate():
    data = row()
    data["transitions"][-1]["action"]["kind"] = "play_card"
    assert not candidate(data)


def test_old_build_rejected_before_replay():
    data = row()
    proof = certify(None, versions() | {"solver_sha256": "old"}, None, data)
    assert proof["rule"] == RULE
    assert proof["reason"] == "e3_unattested_build"
    assert not proof["terminal_verified"] and not data["feedback"]["eligible"]


@pytest.mark.parametrize("reason", ["continuation_difference", "menu_or_action_difference",
                                   "terminal_not_locked", "locked_resources", None])
def test_unwitnessed_or_failed_exact_audit_cannot_promote(monkeypatch, reason):
    data = row()
    original = deepcopy(data)

    def audit(output, identities, spec, replay, mode, worker):
        assert mode == "exact"
        assert replay["feedback"]["status"] == "predicted_win"
        # Even a positive flag is insufficient without live predictor and closure evidence.
        return dict(status="native_difference", terminal_verified=reason is None, reason=reason)

    monkeypatch.setattr(completion.iig.audit, "certify", audit)
    proof = certify(None, versions(), None, data, "semantic")
    assert not proof["terminal_verified"]
    assert data == original
