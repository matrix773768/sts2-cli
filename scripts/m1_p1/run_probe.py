"""Fixed-script experiment using the isolated build and existing EngineClient transport."""
from collections import defaultdict
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

from build_probe import BUILD, ROOT

sys.path.insert(0, str(ROOT / "python"))
import engine_client
from branch_memory import _reader

SEQUENCE = (0, 1, 0)
STOP = {"card_reward", "map_select", "game_over"}


class ProbeFailure(RuntimeError):
    pass


def compare(expected, actual, path="$"):
    if type(expected) is type(actual):
        if isinstance(expected, dict):
            if expected.keys() != actual.keys():
                raise ProbeFailure(f"{path}: missing {sorted(expected.keys() - actual.keys())}, "
                                   f"extra {sorted(actual.keys() - expected.keys())}")
            for key in expected:
                compare(expected[key], actual[key], f"{path}.{key}")
            return
        if isinstance(expected, list) and len(expected) == len(actual):
            for i, (left, right) in enumerate(zip(expected, actual)):
                compare(left, right, f"{path}[{i}]")
            return
        if expected == actual:
            return
    raise ProbeFailure(f"{path}: expected {str(expected)[:400]}, got {str(actual)[:400]}")


def clock():
    return perf_counter() * 1000


@contextmanager
def worker(output, name, lifecycle):
    started = clock()
    engine = engine_client.EngineClient(log_root=output / name, command_timeout=12)
    lifecycle.update(pid=engine.proc.pid, startup=clock() - started)
    try:
        yield engine
    except BaseException:
        engine.close(graceful=False)
        raise
    finally:
        started = clock()
        engine.close()
        lifecycle.update(shutdown=clock() - started, returncode=engine.proc.poll())
        with (engine.log_dir / "stdout.log").open(encoding="utf-8") as stream:
            for line in stream:
                if line.startswith('{"type":"quit_result"'):
                    lifecycle["quit_native"] = json.loads(line)["_probe_ms"]


def run_branch(engine, source, script, output, name, batch=False, expected=None, reset=False):
    times = defaultdict(float)
    native = defaultdict(float)
    per_action = []

    def request(command, kind, label=None):
        start = clock()
        response = engine.send(command)
        elapsed = clock() - start
        if response["type"] != kind:
            raise ProbeFailure(f"{name}: expected {kind}, got {response!r}")
        label = label or command["cmd"]
        exclusive = response.pop("_probe_ms")
        times[label] += elapsed
        for key, value in exclusive.items():
            native[label + "/" + key] += value
        if label == "script_action":
            per_action.append({"action": command["action"], "wall": elapsed, "native": exclusive})
        return response

    def boundary(state, phase):
        if state["decision"] in {"unknown", "combat_turn_timeout"}:
            raise ProbeFailure(f"{name}: unstable {state['decision']}")
        return {
            "state": state,
            "map": request({"cmd": "get_map", "include_start": True}, "map", phase + "_map"),
            "rng": request({"cmd": "probe_rng"}, "rng", phase + "_rng")["value"],
        }

    def save(stage):
        path = output / f"{name}-{stage}.save"
        reply = request({"cmd": "write_continue_save", "path": str(path)}, "save_result", stage + "_save")
        if not reply["success"] or reply["room_type"] != "MapRoom":
            raise ProbeFailure(f"{name}: save outside map")
        document = json.loads(path.read_bytes())
        # Native wall-clock timestamp and elapsed run seconds. Keep all gameplay fields.
        for key in ("save_time", "run_time"):
            if type(document.pop(key)) is not int:
                raise ProbeFailure(f"{name}: unexpected {key}")
        return document

    def progress(stage):
        reply = request({"cmd": "probe_progress"}, "progress", stage + "_progress")
        document = json.loads(reply["value"])
        # Fresh isolated profiles generate different installation identifiers.
        if not isinstance(document.pop("unique_id"), str):
            raise ProbeFailure(f"{name}: unexpected profile ID")
        return document

    start = clock()
    if reset:
        request({"cmd": "probe_reset"}, "reset")
    root_state = request({"cmd": "load_save", "json": source, "lang": "en"}, "decision")
    recovered = clock()
    root = boundary(root_state, "root")
    root_save = save("root")
    root_progress = progress("root")
    if expected is not None:
        compare(expected["root"], root, "$.root")
        compare(expected["root_save"], root_save, "$.root_save")
        compare(expected["root_progress"], root_progress, "$.root_progress")
    room_started = clock()
    if batch:
        steps = request({"cmd": "probe_batch", "actions": script}, "batch")["steps"]
    else:
        steps = []
        for command in script:
            state = request(command, "decision", "script_action")
            steps.append(boundary(state, "script"))
            if state["decision"] in STOP:
                break
    room_elapsed = clock() - room_started
    if len(steps) != len(script) or steps[-1]["state"]["decision"] != "card_reward":
        raise ProbeFailure(f"{name}: unexpected script length or boundary")
    if expected is not None:
        compare(expected["steps"], steps, "$.steps")
    settled = request({"cmd": "action", "action": "skip_card_reward"}, "decision", "settle")
    if settled["decision"] != "map_select":
        raise ProbeFailure(f"{name}: expected settled map, got {settled['decision']}")
    final = boundary(settled, "final")
    final_save = save("final")
    final_progress = progress("final")
    observations = dict(root=root, root_save=root_save, root_progress=root_progress,
                        steps=steps, final=final, final_save=final_save, final_progress=final_progress)
    (output / f"{name}.json").write_text(json.dumps(observations, ensure_ascii=False), encoding="utf-8")
    if expected is not None:
        compare(expected["final"], final, "$.final")
        compare(expected["final_save"], final_save, "$.final_save")
        compare(expected["final_progress"], final_progress, "$.final_progress")
    working, peak = _reader()(engine.proc)
    return observations, dict(
        name=name, pid=engine.proc.pid, times=dict(times), native=dict(native), per_action=per_action,
        recover=recovered-start, room=room_elapsed, wall=clock()-start, working=working, peak=peak,
    )


def check_discard(output, source, reference):
    results = {}
    for mode in ("error", "mismatch", "timeout", "pending_selection"):
        lifecycle = {}
        try:
            with worker(output, mode, lifecycle) as engine:
                loaded = engine.send({"cmd": "load_save", "json": source})
                if loaded["type"] != "decision":
                    raise RuntimeError(f"Fault setup failed: {loaded}")
                if mode == "pending_selection":
                    opened = engine.send({"cmd": "enter_room", "type": "event", "event": "WOOD_CARVINGS"})
                    if opened.get("decision") != "event_choice":
                        raise RuntimeError(f"Fault setup did not enter event: {opened}")
                    pending = engine.send({"cmd": "action", "action": "choose_option",
                                           "args": {"option_index": 0}})
                    if pending.get("decision") != "card_select":
                        raise RuntimeError(f"Fault setup did not suspend a real card selection: {pending}")
                if mode == "timeout":
                    engine._command_timeout = 0.25
                    engine.send({"cmd": "probe_timeout"})
                elif mode == "mismatch":
                    loaded.pop("_probe_ms")
                    wrong = {**reference["root"]["state"], "decision": "injected_mismatch"}
                    compare(wrong, loaded)
                else:
                    cmd = ({"cmd": "probe_reset"} if mode == "pending_selection"
                           else {"cmd": "action", "action": "injected-invalid"})
                    reply = engine.send(cmd)
                    expected_error = ("Reset requires an idle, settled map boundary"
                                      if mode == "pending_selection" else "Unknown action")
                    if reply["type"] == "error" and expected_error in reply["message"]:
                        raise ProbeFailure(reply["message"])
                    raise RuntimeError(f"Unexpected reply to injected {mode}: {reply}")
        except (ProbeFailure, TimeoutError) as error:
            if (mode == "timeout") != isinstance(error, TimeoutError):
                raise
            if lifecycle["returncode"] is None or lifecycle.get("quit_native") is not None:
                raise RuntimeError(f"Faulted worker was not forcibly discarded: {lifecycle}") from error
            results[mode] = {**lifecycle, "reason": str(error).split("; last command=")[0]}
        else:
            raise RuntimeError(f"Injected {mode} was accepted")
    return results


def main():
    if len(sys.argv) != 4:
        raise SystemExit("Usage: run_probe.py M1-B2-summary.json checkpoint.save new-output-directory")
    summary_path, source_path, output = (Path(arg).resolve() for arg in sys.argv[1:])
    output.mkdir(parents=True)
    summary = json.loads(summary_path.read_bytes())
    source_bytes = source_path.read_bytes()
    if sha256(source_bytes).hexdigest() != summary["checkpoint_sha256"]:
        raise ValueError("Historical checkpoint SHA-256 mismatch")
    source = source_bytes.decode("utf-8-sig")
    scripts = [[dict(cmd="action", **action) if "cmd" not in action else action for action in script]
               for script in summary["workload"]["scripts"]]
    if [len(script) for script in scripts] != [26, 26]:
        raise ValueError("Expected M1-B2's two 26-action scripts")

    native_command = engine_client.headless_command()
    dll = BUILD / "bin/Debug/net9.0/Sts2Headless.dll"
    engine_client.headless_command = lambda: [*native_command[:-1], str(dll)]
    records = dict(cold=[], hot=[], batch=[], faults={}, comparisons=0,
                   game_sha256=sha256((ROOT / "lib/sts2.dll").read_bytes()).hexdigest(),
                   probe_sha256=sha256(dll.read_bytes()).hexdigest())
    references = {}
    try:
        for repeat, modes in enumerate((("hot",), ("batch", "hot", "batch"))):
            for index, branch in enumerate(SEQUENCE):
                name = f"cold-{repeat}-{index}"
                lifecycle = {}
                with worker(output, name, lifecycle) as engine:
                    reference, record = run_branch(engine, source, scripts[branch], output, name,
                                                   expected=references.get(branch))
                    references.setdefault(branch, reference)
                records["cold"].append({**record, "lifecycle": lifecycle})
            for trial_index, mode in enumerate(modes):
                trial_name = f"{mode}-{repeat}-{trial_index}"
                lifecycle = {}
                trial = []
                records[mode].append({"branches": trial, "lifecycle": lifecycle})
                started = clock()
                with worker(output, trial_name, lifecycle) as engine:
                    for index, branch in enumerate(SEQUENCE):
                        name = f"{trial_name}-{index}"
                        _, record = run_branch(engine, source, scripts[branch], output, name,
                                               batch=mode == "batch", expected=references[branch],
                                               reset=index > 0)
                        trial.append(record)
                        records["comparisons"] += 1
                lifecycle["wall"] = clock() - started
        records["faults"] = check_discard(output, source, references[0])
        if source_bytes != source_path.read_bytes():
            raise ProbeFailure("Source checkpoint changed")
        if any(record["lifecycle"]["returncode"] != 0 for mode in ("cold", "hot", "batch")
               for record in records[mode]):
            raise ProbeFailure("A successful worker exited abnormally")
    except BaseException as error:
        records["failure"] = str(error)
        raise
    finally:
        (output / "results.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f'{records["comparisons"]} equivalent branches, {len(records["faults"])} discarded workers')


if __name__ == "__main__":
    main()
