"""Exercise cleanup against a child that becomes unresponsive after ready."""
from contextlib import closing
import json
import sys

import pytest

import engine_client


CHILD = """
import sys, time
print('[INFO] CoreCLR ' + sys.argv[1], file=sys.stderr, flush=True)
print('{"type":"ready"}', flush=True)
for line in sys.stdin:
    if 'hang' in line:
        time.sleep(30)
    elif 'quit' in line:
        break
    else:
        print('{"type":"ok"}', flush=True)
"""


def configure(monkeypatch, version="9.0.7"):
    monkeypatch.setenv("STS2_DOTNET_VERSION", "9.0.7")
    monkeypatch.setattr(engine_client, "headless_command",
                        lambda: [sys.executable, "-u", "-c", CHILD, version])


def test_timeout_reaps_child_before_next_worker(monkeypatch, tmp_path):
    configure(monkeypatch)
    failed = engine_client.EngineClient(log_root=tmp_path, command_timeout=0.2)
    with pytest.raises(TimeoutError, match="phase=synthetic_start"):
        failed.send({"cmd": "synthetic_start", "spec": "hang"})
    evidence = json.loads((failed.log_dir / "lifecycle.json").read_bytes())
    assert evidence["exit_code"] is not None and evidence["io_threads_stopped"]
    assert not evidence["graceful_requested"]
    with closing(engine_client.EngineClient(log_root=tmp_path)) as healthy:
        assert healthy.send({"cmd": "probe"})["type"] == "ok"
    assert healthy.proc.returncode == 0


def test_wrong_runtime_is_reaped_during_startup(monkeypatch, tmp_path):
    configure(monkeypatch, "9.0.8")
    with pytest.raises(RuntimeError, match="Unexpected CoreCLR runtime"):
        engine_client.EngineClient(log_root=tmp_path)
    log, = tmp_path.glob("game-*/lifecycle.json")
    evidence = json.loads(log.read_bytes())
    assert evidence["last_phase"] == "runtime_attestation"
    assert evidence["exit_code"] is not None and evidence["io_threads_stopped"]
