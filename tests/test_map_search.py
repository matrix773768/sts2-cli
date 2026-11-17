"""Tests for map-edge selection, evaluation, and native one-room lookahead."""
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from branch_scheduler import BranchResult
import map_search
from map_search import Heuristic, SearchConfig, search_map
from search_env import Build, Checkpoint, ReplayStep, SearchPosition
from test_save_load import requires_engine
from test_search_env_integration import root


def encoded(value):
    return json.dumps(value).encode()


def map_root(tmp_path):
    nodes = [{"col": i, "row": 1, "type": "Monster"} for i in (3, 1)]
    context = {"room_type": "Map", "act": 1, "floor": 1}
    player = {"hp": 80, "max_hp": 80, "gold": 99,
              "deck": [{"id": "CARD.STRIKE", "upgraded": False}]}
    state = {"decision": "map_select", "context": context, "act": 1, "floor": 1,
             "player": player, "choices": nodes}
    world = {"context": context, "rows": [nodes], "boss": {"col": 3, "row": 9},
             "starting_point": {"col": 2, "row": 0, "children": nodes},
             "current_coord": {"col": 2, "row": 0}}
    observation, world_map = encoded(state), encoded(world)
    return Checkpoint(tmp_path / "save", "save", Build("build", "dll", "engine", 1), "9", "test",
                      "en", observation, world_map, sha256(observation).hexdigest(),
                      sha256(world_map).hexdigest(), ("fixture",))


def completed(task, *, hp=76, gold=119, terminal=False):
    selected = task.policy({"decision": "map_select"})
    coords = selected["args"]
    state = {"decision": "game_over" if terminal else "map_select",
             "context": {"room_type": "Map", "act": 1, "floor": 2},
             "player": {"hp": hp, "max_hp": 80, "gold": gold,
                        "deck": [{"id": "CARD.NEW", "upgraded": True}]}}
    step = ReplayStep(encoded(selected), encoded(state), encoded({"current_coord": coords}))
    return BranchResult(task.task_id, "terminal" if terminal else "boundary", actions=1,
                        observation=state, position=SearchPosition(task.root, (step,)),
                        victory=False if terminal else None)


def test_scores_and_stable_tie(tmp_path, monkeypatch):
    root = map_root(tmp_path)
    config = SearchConfig(max_workers=4, evaluator=Heuristic(hp_weight=2, gold_weight=0.5))

    def batch(tasks, **kwargs):
        assert [task.task_id for task in tasks] == ["1,1", "3,1"]
        assert all(task.stop_at == ("map_select",) for task in tasks)
        assert kwargs["max_workers"] == 4
        return [completed(task) for task in tasks]

    monkeypatch.setattr(map_search, "run_batch", batch)
    search = search_map(root, config)
    one, three = search.candidates
    assert search.recommended_action == one.node.action()
    assert (one.node.col, three.node.col) == (1, 3)
    assert one.score == three.score
    assert one.score.total == 2 and one.score.components == {"hp": -8, "gold": 10}
    assert one.changes["deck"] == {
        "added": [{"id": "CARD.NEW", "upgraded": True}],
        "removed": [{"id": "CARD.STRIKE", "upgraded": False}],
    }
    assert one.resources.coord == (1, 1)

    monkeypatch.setattr(map_search, "run_batch", lambda tasks, **_: [
        completed(tasks[0]), completed(tasks[1], hp=77)
    ])
    assert search_map(root, config).recommended_action == three.node.action()


def test_terminal_death_is_ranked_below_survival(tmp_path, monkeypatch):
    monkeypatch.setattr(map_search, "run_batch", lambda tasks, **_: [
        completed(tasks[0], hp=0, gold=10_000, terminal=True), completed(tasks[1])
    ])
    search = search_map(map_root(tmp_path))
    assert search.candidates[0].outcome == "death"
    assert search.candidates[0].score.total > search.candidates[1].score.total
    assert search.recommended_action["args"]["col"] == 3


@pytest.mark.parametrize("status", ["engine_error", "timeout", "action_budget", "unsupported", "branch_budget"])
def test_incomplete_results_never_recommend(tmp_path, monkeypatch, status):
    def batch(tasks, **_):
        results = [completed(tasks[0])]
        if status != "branch_budget":
            results.append(BranchResult(tasks[1].task_id, status,
                                        observation={"decision": "event_choice"}))
        return results

    monkeypatch.setattr(map_search, "run_batch", batch)
    config = SearchConfig(max_branches=1 if status == "branch_budget" else 2)
    search = search_map(map_root(tmp_path), config)
    assert search.recommended_action is None
    assert "1/2" in search.reason
    assert search.candidates[0].score is not None
    assert search.candidates[1].score is None and search.candidates[1].branch.status == status


@requires_engine
def test_map_lookahead_serial_parallel(root, tmp_path):
    env, checkpoint = root
    original = checkpoint.path.read_bytes()
    initial = env.observe()
    config = SearchConfig(checkpoint_dir=tmp_path, log_root=tmp_path / "lookahead", max_workers=1)
    serial = search_map(checkpoint, config)
    parallel = search_map(checkpoint, replace(config, max_workers=4))
    assert checkpoint.path.read_bytes() == original
    assert sha256(original).hexdigest() == checkpoint.sha256
    assert env.observe() == initial
    nodes = {(n["col"], n["row"]) for n in initial["choices"]}
    assert nodes == {(c.node.col, c.node.row) for c in serial.candidates}
    assert parallel.recommended_action == serial.recommended_action
    picked = serial.recommended_action["args"]
    assert (picked["col"], picked["row"]) in nodes
    for left, right in zip(serial.candidates, parallel.candidates):
        assert left.branch.returncode == right.branch.returncode == 0
        assert left.branch.log_dir != right.branch.log_dir
        assert left.outcome == right.outcome == "map"
        assert left.branch.position == right.branch.position
        assert left.resources == right.resources and left.changes == right.changes
        assert left.score == right.score
        assert left.branch.observation["decision"] == "map_select"
        steps = left.branch.position.prefix
        assert any(json.loads(s.action)["action"] == "select_card_reward" for s in steps)
    print(json.dumps({
        "serial_seconds": serial.elapsed, "parallel_seconds": parallel.elapsed,
        "recommended": parallel.recommended_action,
        "candidates": [{"action": c.node.action(), "score": c.score.total,
                        "components": c.score.components, "rank": c.score.outcome_rank,
                        "changes": c.changes, "hp": c.resources.hp, "max_hp": c.resources.max_hp,
                        "gold": c.resources.gold, "steps": c.branch.actions,
                        "seconds": c.branch.elapsed} for c in parallel.candidates],
    }, ensure_ascii=False))
