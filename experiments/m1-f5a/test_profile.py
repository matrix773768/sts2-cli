from probe import compare
from report import distribution, evidence


def test_prediction_comparison_retains_route_and_checkpoint():
    left = {"routes": [{"rollout_ms": 2, "actions": [1]}],
            "checkpoints": [{"hot_ms": 1, "transitions": 10}]}
    right = {"routes": [{"rollout_ms": 8, "actions": [1]}],
             "checkpoints": [{"hot_ms": 3, "transitions": 10}]}
    assert compare(left, right) == []
    right["routes"][0]["actions"] = [2]
    assert compare(left, right) == [
        {"field": "$.routes[0].actions[0]", "expected": 1, "actual": 2}]


def test_evidence_keeps_native_acceptance_and_cost():
    row = {"elapsed_ms": 5, "total_charged": 10,
           "native": {"strict_terminal": True, "matched_actions": 4, "native_ms": 2}}
    assert evidence(row) == {"total_charged": 10,
                             "native": {"strict_terminal": True, "matched_actions": 4}}


def test_distribution_reports_sample_count_and_tails():
    result = distribution([None, 1, 2, 3])
    assert (result["n"], result["median"], result["p90"]) == (3, 2, 2.8)
