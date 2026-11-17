"""Transport lifecycle tests using a local protocol stub without game DLLs."""
import sys
import time

import pytest

import engine_client
from engine_client import EngineClient
from search_env import CheckpointError, EngineFailure, SearchEnv, _validate_boundary


@pytest.fixture
def stub(tmp_path, monkeypatch):
    script = tmp_path / "stub.py"
    script.write_text("""
import json
import sys
import time
print('[INFO] CoreCLR 9.0.7', file=sys.stderr, flush=True)
print(json.dumps({'type': 'ready', 'version': 'stub'}), flush=True)
for line in sys.stdin:
    command = json.loads(line)
    name = command['cmd']
    if name in ('quit', 'eof'):
        break
    if name == 'stall' or command.get('action') == 'stall':
        time.sleep(60)
    if name == 'start_run':
        result = {'type': 'decision', 'decision': 'event_choice'}
    elif command.get('action') == 'terminal':
        result = {'type': 'decision', 'decision': 'game_over', 'victory': False}
    else:
        result = {'type': 'error', 'message': 'stub action failure'}
    print(json.dumps(result), flush=True)
""", encoding="utf-8")
    monkeypatch.setattr(engine_client, "headless_command", lambda: [sys.executable, str(script)])
    return tmp_path


@pytest.mark.parametrize("command, error", [("stall", TimeoutError), ("eof", RuntimeError)])
def test_transport_reaps_failed_process(stub, command, error):
    client = EngineClient(log_root=stub, command_timeout=0.25)
    with pytest.raises(error):
        client.send({"cmd": command})
    assert client.proc.poll() is not None
    client.close()
    with pytest.raises(RuntimeError, match="closed"):
        client.send({"cmd": command})


def test_transport_reaps_after_run_deadline(stub):
    client = EngineClient(log_root=stub, deadline=time.monotonic() + 5)
    client._deadline = time.monotonic() - 1
    with pytest.raises(TimeoutError, match="deadline"):
        client.send({"cmd": "stall"})
    assert client.proc.poll() is not None
    assert not (client.log_dir / "commands.jsonl").exists()


@pytest.mark.parametrize("name", ["terminal", "fail", "stall"])
def test_search_terminal_or_native_failure(stub, monkeypatch, name):
    monkeypatch.setattr(SearchEnv, "_build", lambda self: "stub")
    with SearchEnv(game_build="stub", checkpoint_dir=stub, log_root=stub,
                   command_timeout=0.5) as env:
        observation = env.reset(seed="test")
        process = env._engine.proc
        observation["decision"] = "corrupted"
        assert env.observe()["decision"] == "event_choice"
        if name == "terminal":
            assert env.step({"action": name})["victory"] is False
            assert process.poll() is None
        elif name == "stall":
            with pytest.raises(TimeoutError):
                env.step({"action": name})
            assert process.poll() is not None
            with pytest.raises(EngineFailure, match="No active decision"):
                env.observe()
        else:
            with pytest.raises(EngineFailure, match="stub action failure"):
                env.step({"action": name})
            assert process.poll() is not None
        with pytest.raises(EngineFailure, match="No active nonterminal"):
            env.step({"action": name})
    env.close()
    env.close()
    assert process.poll() is not None
    if name == "terminal":
        assert process.returncode == 0


@pytest.mark.parametrize("case", ["ancient", "extra_choice", "stale_coord", "act_one", "conflicting_floor", "duplicate_node"])
def test_unvisited_map_admission(case):
    context = {"room_type": "Map", "act": 2, "floor": 0}
    start = {"col": 3, "row": 0, "type": "Ancient"}
    monster = {"col": 3, "row": 1, "type": "Monster"}
    world = {"context": context, "starting_point": start, "rows": [[monster]],
             "boss": {"col": 3, "row": 8, "type": "Boss"}}
    state = {"decision": "map_select", "context": context, "floor": 0,
             "act": 2, "choices": [start]}
    if case == "ancient":
        _validate_boundary(state, world)
        return
    if case == "extra_choice":
        state["choices"].append(monster)
    elif case == "stale_coord":
        world["current_coord"] = {"col": 9, "row": 9}
    elif case == "act_one":
        context["act"] = state["act"] = 1
    elif case == "conflicting_floor":
        context["floor"] = 1
    else:
        world["rows"].append([monster.copy()])
    with pytest.raises(CheckpointError, match="Unsupported map checkpoint boundary"):
        _validate_boundary(state, world)


def test_worker_start_failure_reaps_process(stub, monkeypatch):
    processes = []
    popen = engine_client.subprocess.Popen

    def capture(*args, **kwargs):
        proc = popen(*args, **kwargs)
        processes.append(proc)
        return proc

    start = engine_client.threading.Thread.start

    def fail_writer(thread):
        if "_write_commands" in thread.name:
            raise RuntimeError("writer could not start")
        start(thread)

    monkeypatch.setattr(engine_client.subprocess, "Popen", capture)
    monkeypatch.setattr(engine_client.threading.Thread, "start", fail_writer)
    with pytest.raises(RuntimeError, match="writer could not start"):
        EngineClient(log_root=stub)
    assert len(processes) == 1
    process = processes[0]
    assert process.poll() is not None
    assert process.stdin.closed and process.stdout.closed and process.stderr.closed
