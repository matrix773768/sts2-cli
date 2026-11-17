"""Solve twice without touching the root, then replay once in a fresh native process."""
from build import ROOT, BUILD, SOLVER
from hashlib import sha256
import os
import sys
import json
from time import perf_counter

sys.path.insert(0, str(ROOT / "python"))
import engine_client

def main():
    os.environ["I1_SOLVER"] = str(SOLVER)
    os.environ.setdefault("I1_RITSU", str(
        ROOT.home() / "Desktop/STEAM/steamapps/workshop/content/2868840/3747602295"))
    os.environ.setdefault("STS2_DOTNET", str(ROOT / "logs/m1-review-dotnet/dotnet.exe"))
    os.environ.setdefault("STS2_DOTNET_VERSION", "9.0.7")
    os.environ["DOTNET_GCHeapHardLimit"] = "10000000"  # hexadecimal, 256 MiB managed heap
    native = engine_client.headless_command()
    dll = BUILD / "Headless/bin/Debug/net9.0/OfflineSearchHarness.dll"
    engine_client.headless_command = lambda: [*native[:-1], str(dll)]
    output = ROOT / "logs/m1-i1"
    output.mkdir(exist_ok=True)
    os.environ["I1_LOG"] = str(output)
    checkpoint, = (ROOT / "logs/m1-b2-benchmark/checkpoints").glob("*.save")
    source = checkpoint.read_bytes()
    assert sha256(source).hexdigest() == "05c527152891c30807233fdfc4837ac2c4b0a6793fbedd600bc0c1ca6fea5295"
    trace = []
    deadline = perf_counter() + 45

    def save():
        (output / "trace.json").write_text(json.dumps(trace, indent=2), encoding="utf-8")

    def request(engine, cmd, **args):
        start = perf_counter()
        if start >= deadline:
            raise TimeoutError("Experiment deadline")
        engine._command_timeout = min(12, deadline - start)
        result = engine.send(dict(cmd=cmd, **args))
        trace.append(dict(cmd=cmd, args={k: v for k, v in args.items() if k != "json"},
                          elapsed_ms=(perf_counter()-start)*1000, result=result))
        save()
        if result.get("type") == "error":
            raise RuntimeError(result["message"])
        return result

    def open_combat(engine):
        assert request(engine, "load_save", json=source.decode("utf-8"), lang="en")["decision"] == "map_select"
        state = request(engine, "action", action="select_map_node", args=dict(col=2, row=1))
        assert state["decision"] == "combat_play"
        return state

    def check(index, expected, actual):
        if expected != actual:
            diffs = [dict(enemy=i, fields=sorted(k for k in a.keys() | b.keys()
                                                if a.get(k) != b.get(k)))
                     for i, (a, b) in enumerate(zip(expected, actual)) if a != b]
            trace.append(dict(first_difference=index, fields=diffs, expected=expected, actual=actual))
            save()
            raise AssertionError(f"First difference at {index}: {diffs}; see {output / 'trace.json'}")

    def launch():
        start = perf_counter()
        engine = engine_client.EngineClient(log_root=output, command_timeout=12)
        trace.append(dict(start_ms=(perf_counter()-start)*1000))
        return engine

    engine = launch()
    try:
        root = open_combat(engine)
        before = request(engine, "i1_begin")["state"]
        cold, warm = (request(engine, "i1_capture") for _ in range(2))
        after = request(engine, "i1_state")["state"]
        check("prediction root", cold["root"], before)
        check("source unchanged", before, after)
        for field in ("actions", "root", "frames"):
            assert cold[field] == warm[field], field
    finally:
        engine.close()

    engine = launch()
    try:
        assert open_combat(engine) == root
        check("restored root", cold["root"], request(engine, "i1_begin")["state"])
        for i, (action, expected) in enumerate(zip(cold["actions"], cold["frames"]), 1):
            step = request(engine, "i1_step", action=action)
            check(i, expected, step["state"])
            last = i == len(cold["actions"])
            assert step["terminal"] == last
            decision = step["decision"]
            assert decision.get("type") != "error", decision
            assert decision.get("decision") == ("card_reward" if last else "combat_play"), decision
        settled = request(engine, "action", action="skip_card_reward")
        assert settled["decision"] == "map_select", settled
        assert (settled["player"]["hp"], settled["player"]["gold"]) == (80, 116)
    finally:
        engine.close()
        assert checkpoint.read_bytes() == source
    print(f"{len(cold['actions'])} actions matched; native victory and reward settlement; {output / 'trace.json'}")

if __name__ == "__main__":
    main()
