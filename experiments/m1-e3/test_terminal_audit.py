import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def test_difference_is_terminal_only_and_labels_match_at_combat_boundary():
    with gzip.open(HERE / "results.json.gz", "rt", encoding="utf-8") as stream:
        cases = json.load(stream)["cases"]
    assert set(cases) == {"predator", "predator_with_potion", "enemy_side"}
    for name, case in cases.items():
        *prefix, terminal = case["samples"]
        assert all(not sample["terminal"] and not sample["differences"] for sample in prefix)
        assert case["preparation"]["predicted_win"] and terminal["terminal"]
        assert terminal["decision"]["decision"] == "card_reward"
        assert terminal["step"] == case["original"]["diagnosis"]["first_step"]
        assert terminal["differences"] == case["original"]["diagnosis"]["fields"]
        assert terminal["terminal_window"]["enemy_hp"] == 0
        for predicted, native in zip(terminal["predicted"], terminal["native"], strict=True):
            for field in ("player_hp", "player_max_hp", "player_gold", "player_potions",
                          "rng_counters", "player_card_upgrades"):
                assert predicted[field] == native[field], (name, field)
        assert terminal["decision"]["player"]["hp"] == terminal["native"][0]["player_hp"]
        if name.startswith("predator"):
            assert prefix[0]["native"][0]["player_powers"]["DRAW_CARDS_NEXT_TURN_POWER"] == 2
            assert "DRAW_CARDS_NEXT_TURN_POWER" not in prefix[4]["native"][0]["player_powers"]
        else:
            assert prefix[-1]["native"][0]["enemy_powers"]["POISON_POWER"] == 4
            assert terminal["before_window"]["side"] == "Player"
            assert terminal["terminal_window"]["side"] == "Enemy"
            assert terminal["before_window"]["card_plays"] == terminal["terminal_window"]["card_plays"]
