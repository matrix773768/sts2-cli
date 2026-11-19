from public_target import Enemy, Move, Observation, decide, observe


def test_public_projection_uses_revealed_total_and_ignores_hidden_fields():
    state = {
        "player": {"block": 0, "rng": "ignored"},
        "enemies": [{"index": 1, "hp": 20, "block": 1,
                     "intents": [{"damage": 3, "hits": 2}], "next_move": "ignored"}],
        "hand": [{"index": 0, "type": "Attack", "can_play": True, "cost": 1,
                  "target_type": "AnyEnemy", "stats": {"repeat": 2},
                  "damage_by_target": [{"target_index": 1, "damage": 5, "total_damage": 10}]}],
        "draw_order": "ignored",
    }
    assert observe(state) == Observation(0, (Enemy(1, 20, 1, 6),), (Move(0, 1, 10, 0, 0, 1, False),))


def test_threat_only_retargets_nonlethal_card():
    enemies = (Enemy(0, 20, 0, 0), Enemy(1, 20, 1, 8))
    weaker = Move(0, 1, 4, 0, 0, 1, False)
    ordinary = Move(0, 0, 7, 0, 0, 1, False)
    view = Observation(0, enemies, (ordinary, weaker))
    assert decide(view, "PUBLIC_SCORE_V1")["args"]["target_index"] == 0
    assert decide(view, "PUBLIC_THREAT_V1")["args"]["target_index"] == 1
    lethal = Move(0, 0, 20, 0, 0, 1, False)
    assert decide(Observation(0, enemies, (lethal, weaker)), "PUBLIC_THREAT_V1")["args"]["target_index"] == 0
