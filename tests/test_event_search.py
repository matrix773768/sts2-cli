"""Exercise native event lookahead on the existing Regent run_4 route."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

import event_search
from branch_scheduler import BranchResult
from event_search import _EventPolicy, _options, _selection_action, search_event
from map_search import Resources, Score, SearchConfig
from search_env import SearchEnv
from test_save_load import requires_engine


def test_event_options_and_loop_guard():
    context = {"room_type": "Event", "act": 1, "floor": 3}
    event = {"decision": "event_choice", "event_name": "Fixture", "context": context,
             "options": [{"index": i, "title": str(i), "text_key": f"FIXTURE.{i}", "is_locked": locked}
                         for i, locked in ((2, False), (1, True), (0, False))]}
    options = _options(event)
    assert [o.index for o in options] == [0, 2]
    resources = Resources(50, 80, 99, 1, 3, (2, 2), (), (), ())
    policy = _EventPolicy(options[1], "Fixture", resources)
    assert policy(event) == options[1].action()
    next_page = {**event, "options": [event["options"][-1]]}
    assert policy(next_page) == options[0].action()
    assert policy(next_page) is None and policy.reason == "Repeated event decision"


@pytest.mark.parametrize(("state", "expected"), [
    ({"decision": "card_select", "min_select": 2, "max_select": 3,
      "cards": [{"index": 2}, {"index": 0}, {"index": 1}]}, ("select_cards", {"indices": "0,1"})),
    ({"decision": "card_select", "min_select": 0, "max_select": 1, "cards": []}, ("skip_select", {})),
    ({"decision": "card_reward", "from_event": True, "cards": [{"index": 2}]},
     ("select_card_reward", {"card_index": 2})),
    ({"decision": "bundle_select", "bundles": [{"index": 1}, {"index": 0}]},
     ("select_bundle", {"bundle_index": 0})),
    ({"decision": "combat_play"}, None),
    ({"decision": "card_reward", "cards": [{"index": 0}]}, None),
    ({"decision": "card_select", "min_select": 2, "max_select": 2, "cards": [{"index": 0}]}, None),
])
def test_event_continuation_uses_offered_choices(state, expected):
    result = _selection_action(state)
    assert result == (None if expected is None else dict(action=expected[0], args=expected[1]))


@requires_engine
def test_event_lookahead_serial_parallel(tmp_path, monkeypatch):
    fixture = Path(__file__).with_name("particle_wall_run_4.jsonl")
    commands = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
    config = SearchConfig(checkpoint_dir=tmp_path, log_root=tmp_path / "branches", max_workers=1)
    with SearchEnv(game_build="26660232", checkpoint_dir=tmp_path, log_root=tmp_path / "caller") as env:
        start = {k: v for k, v in commands[0].items() if k != "cmd"}
        env.reset(**start)
        for command in commands[1:23]:
            state = env.step(command)
        assert state["decision"] == "map_select" and state["floor"] == 2
        checkpoint = env.save_checkpoint()
        source = checkpoint.path.read_bytes()
        event = env.step(commands[23])
        assert event["decision"] == "event_choice"
        position = env.position()
        available = _options(event)
        assert [o.text_key.rsplit(".", 1)[-1] for o in available] == [
            "NAB_THE_MAP", "SLOWLY_FIND_AN_EXIT",
        ]

        serial = search_event(position, config)
        parallel = search_event(position, replace(config, max_workers=4))
        assert env.observe() == event and env.position() == position
        assert checkpoint.path.read_bytes() == source and sha256(source).hexdigest() == checkpoint.sha256
        assert serial.recommended_action == parallel.recommended_action
        for left, right in zip(serial.candidates, parallel.candidates):
            assert left.option == right.option
            assert left.outcome == right.outcome == "map"
            assert left.branch.returncode == right.branch.returncode == 0
            assert left.branch.log_dir != right.branch.log_dir
            assert left.branch.position == right.branch.position
            assert left.resources == right.resources and left.score == right.score
            assert left.branch.actions == right.branch.actions == 1
        take, exit_ = parallel.candidates
        assert take.changes["hp"] == 0 and take.changes["gold"] == 0
        assert [card["id"] for card in take.changes["deck"]["added"]] == ["CARD.SPOILS_MAP"]
        assert exit_.changes["hp"] == -event["options"][exit_.option.index]["vars"]["Damage"]
        assert exit_.changes["gold"] == 0 and len(exit_.changes["potions"]["added"]) == 1
        assert take.score.total == 0 and exit_.score.total == exit_.changes["hp"] < 0
        assert parallel.recommended_action == take.option.action()
        print(json.dumps({"event": parallel.event_name, "serial_seconds": serial.elapsed,
                          "parallel_seconds": parallel.elapsed, "recommended": parallel.recommended_action,
                          "options": [{"index": c.option.index, "title": c.option.title,
                                       "components": c.score.components, "score": c.score.total,
                                       "changes": c.changes, "seconds": c.branch.elapsed}
                                      for c in parallel.candidates]}, ensure_ascii=False))

        # Reverse the ordering via a replacement evaluator on the same verified outcomes,
        # without launching extra native processes.
        monkeypatch.setattr(event_search, "run_batch", lambda *_a, **_kw: [
            c.branch for c in parallel.candidates
        ])
        reversed_search = search_event(position, replace(
            config, evaluator=lambda before, after, _: Score(1, {"hp_loss": before.hp - after.hp})
        ))
        assert reversed_search.recommended_action == exit_.option.action()
        monkeypatch.setattr(event_search, "run_batch", lambda *_a, **_kw: [
            take.branch, BranchResult("1", "timeout", error="test deadline")
        ])
        incomplete = search_event(position, config)
        assert incomplete.recommended_action is None and incomplete.candidates[1].score is None
        assert incomplete.candidates[1].reason == "test deadline"
