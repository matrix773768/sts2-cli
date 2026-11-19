"""Guard the fixed binary identity, native parity and unrelated search regressions."""
import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
POWER = "DRAW_CARDS_NEXT_TURN_POWER"


def evidence():
    with gzip.open(HERE / "results.json.gz", "rt", encoding="utf-8") as stream:
        return json.load(stream)


def test_patched_solver_matches_independent_native_frames():
    data = evidence()
    assert data["build"]["patched_sha256"] != data["build"]["frozen_sha256"]
    for name in ("predator", "predator_with_potion", "other_primary_survives"):
        case = data["cases"][name]
        assert case["native_identity"]["sha256"] == data["build"]["frozen_sha256"]
        assert case["prediction_identities"]["fixed"]["sha256"] == data["build"]["patched_sha256"]
        assert all(not sample["fixed"]["differences"] for sample in case["rows"])
        terminal = case["rows"][-1]
        if name == "other_primary_survives":
            assert not terminal["terminal"]
            assert [enemy["enemy_hp"] for enemy in terminal["native"]] == [0, 36]
            assert terminal["native"][0]["player_powers"][POWER] == 2
        else:
            assert terminal["terminal"] and terminal["decision"]["decision"] == "card_reward"
            assert terminal["frozen"]["differences"]
            assert POWER not in terminal["fixed"]["predicted"][0]["player_powers"]
    samples = data["cases"]["predator"]["rows"]
    assert samples[0]["native"][0]["enemy_hp"] == 29
    assert samples[0]["fixed"]["predicted"][0]["player_powers"][POWER] == 2
    assert POWER not in samples[4]["fixed"]["predicted"][0]["player_powers"]


def test_enemy_side_remains_strictly_rejected_and_unrelated_search_is_stable():
    data = evidence()
    final = data["cases"]["enemy_side"]["rows"][-1]
    fields = [d["field"] for d in final["fixed"]["differences"]]
    assert fields == ["$[0].exact_continuation_state.AttackStarts", "$[0].exact_continuation_state.Y"]
    assert final["frozen"]["differences"] == final["fixed"]["differences"]
    for name in ("unrelated", "enemy_side"):
        assert data["search"][name]["diff"] == {"first": [], "quality": []}
    for name in ("predator", "predator_with_potion"):
        pair = data["search"][name]
        assert pair["frozen"]["first"]["status"] == pair["fixed"]["first"]["status"] == "predicted_win"
        assert pair["fixed"]["quality"] is not None
        assert pair["frozen"]["selected"] == pair["fixed"]["selected"]
        for stage in ("first", "quality"):
            assert pair["frozen"][stage]["transitions"] == pair["fixed"][stage]["transitions"]
        assert pair["frozen"]["first"]["actions"] == pair["fixed"]["first"]["actions"]
        assert pair["frozen"]["quality"]["attempts"] == pair["fixed"]["quality"]["attempts"]
        for before, after in zip(pair["frozen"]["quality"]["candidates"],
                                 pair["fixed"]["quality"]["candidates"], strict=True):
            assert {k: v for k, v in before.items() if k != "stamps"} == (
                {k: v for k, v in after.items() if k != "stamps"})
            assert before["stamps"][:-1] == after["stamps"][:-1]
            if before["stamps"][-1] != after["stamps"][-1]:
                assert before["predator_terminal"]
