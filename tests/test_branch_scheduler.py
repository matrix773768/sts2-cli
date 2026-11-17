"""Focused scheduler tests using both controlled clients and a genuine map fixture."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import threading
import time

import pytest

import branch_scheduler
from branch_scheduler import BranchTask, run_batch
from engine_client import EngineCancelled, EngineClient
from search_benchmark import _stats, make_workload
from search_env import SearchPosition
from test_save_load import requires_engine
from test_search_env_unit import stub


def test_scheduler_statuses_and_fault_isolation(tmp_path, monkeypatch):
    class Environment:
        def __init__(self, *, deadline, **_):
            self.deadline = deadline
            self.closed = False
            sessions.append(self)

        def reset(self, *, checkpoint):
            return {"decision": "map_select"}

        def step(self, action):
            if action["action"] == "fail":
                raise RuntimeError("native error")
            if action["action"] == "timeout":
                raise TimeoutError("request expired")
            return {"decision": "game_over", "victory": False}

        def position(self):
            return "trace"

        def close(self):
            self.closed = True

    sessions = []
    monkeypatch.setattr(branch_scheduler, "SearchEnv", Environment)
    tasks = [BranchTask(None, actions=({"action": name},), task_id=name)
             for name in ("fail", "terminal", "timeout")]
    tasks += [BranchTask(None, actions=(), max_actions=0), BranchTask(None, policy=lambda _: None)]
    results = run_batch(tasks, game_build="test", checkpoint_dir=tmp_path, max_workers=2)
    assert [r.status for r in results] == [
        "engine_error", "terminal", "timeout", "action_budget", "unsupported",
    ]
    assert [r.victory for r in results] == [None, False, None, None, None]
    assert len(sessions) == len(tasks) and all(env.closed for env in sessions)
    assert _stats([1, 5, 3, 7]) == {"n": 4, "p50": 4, "p95": 7}


def test_cancel_interrupts_ipc_and_reaps(stub):
    cancelled = threading.Event()
    client = EngineClient(log_root=stub, cancelled=cancelled.is_set)
    timer = threading.Timer(0.15, cancelled.set)
    timer.start()
    try:
        with pytest.raises(EngineCancelled):
            client.send({"cmd": "stall"})
        assert client.proc.poll() is not None
        results = run_batch([BranchTask(None, actions=())], game_build="test", checkpoint_dir=stub,
                            cancel_event=cancelled)
        assert results[0].status == "canceled" and not results[0].attempted
    finally:
        timer.cancel()
        timer.join()
        client.close()


def test_batch_deadline_stops_launching(tmp_path, monkeypatch):
    class Environment:
        def __init__(self, *, deadline, **_):
            self.deadline = deadline

        def reset(self, **_):
            time.sleep(max(0, self.deadline - time.monotonic()) + 0.01)
            raise TimeoutError("deadline")

        def close(self):
            pass

    monkeypatch.setattr(branch_scheduler, "SearchEnv", Environment)
    results = run_batch([BranchTask(None, actions=())] * 3, game_build="test",
                        checkpoint_dir=tmp_path, timeout=0.25)
    assert all(r.status == "batch_deadline" for r in results)
    assert [r.attempted for r in results] == [True, False, False]


@requires_engine
def test_parallel_branches_match_serial_and_reap(tmp_path):
    config = dict(game_build="26660232", checkpoint_dir=tmp_path / "saves", log_root=tmp_path / "engines")
    root, references, _ = make_workload(config, time.monotonic() + 90)
    original = root.path.read_bytes()
    foreign_root = replace(root, sha256="incorrect")
    seen = set()
    for workers, scripts in ((1, [0]), (2, [1, 0]), (4, [0, 1, 0, 1, None])):
        tasks = []
        for i, script in enumerate(scripts):
            if script is None:
                tasks.append(BranchTask(foreign_root, actions=()))
                continue
            expected = references[script]
            # Also exercise resuming a verified in-room SearchPosition.
            offset = 1 if workers == 4 and i == 2 else 0
            start = SearchPosition(root, expected.prefix[:offset]) if offset else root
            tasks.append(BranchTask(start, actions=tuple(json.loads(s.action) for s in expected.prefix[offset:])))
        results = run_batch(tasks, **config, max_workers=workers)
        for script, result in zip(scripts, results):
            if script is None:
                assert result.status == "checkpoint_error" and result.pid is None
                continue
            assert result.successful and result.position == references[script], result.error
            assert result.returncode == 0 and result.log_dir not in seen
            seen.add(result.log_dir)
            log_dir = Path(result.log_dir)
            assert all((log_dir / name).is_dir() for name in ("cwd", "profile", "temp"))
        assert root.path.read_bytes() == original and sha256(original).hexdigest() == root.sha256
