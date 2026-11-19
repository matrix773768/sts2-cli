"""Cold, same-root and warm multi-worker qualification on declared development roots."""
import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from pathlib import Path
import runpy
from time import perf_counter

from environment import Episode, choose

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
n1 = runpy.run_path(str(HERE.parent / "m1-n1/benchmark_n1.py"))
s3a, bank = n1["s3a"], n1["bank"]
s3a.HOST = "m1-n2a-build"
SPECIAL = n1["SPECIAL"]


def ms(start):
    return (perf_counter() - start) * 1000


def cases():
    entries = [item for item in n1["inputs"]() if item["synthetic"]]
    for predicate in (
        lambda c: c.get("rule") == "strength",
        lambda c: c.get("rule") == "shiv",
        lambda c: c["id"] == SPECIAL,
        lambda c: c.get("rule") == "dexterity",
    ):
        yield next(item for item in entries if predicate(item["case"]))


@contextmanager
def worker(output, item, versions, lifecycle):
    with ExitStack() as stack:
        start = perf_counter()
        game, identity = s3a.attested(output, stack, versions)
        launched = ms(start)
        surfaces, phases = s3a.b1b.synth.capture(game, item["case"]["spec"])
        root = bank.stamp(surfaces)
        if item.get("root_sha256") and root != item["root_sha256"]:
            raise ValueError("Root identity changed")
        record = dict(id=item["case"]["id"], root_sha256=root, loaded=identity,
                      launch_ms=launched, build=phases)
        lifecycle.append(record)
        yield game, surfaces
        start = perf_counter()
    record["recycle_ms"] = ms(start)


def execute(game, item, defense_first, phase):
    episode = Episode(game)
    before = game.request("f1_audit")
    started = perf_counter()
    trajectory = []
    decision_ms = 0
    try:
        reset = perf_counter()
        try:
            observation = episode.reset()
        except bank.f1.i2.StopRun as error:
            if "PredictionUnsupportedException" not in str(error):
                raise
            episode.state = dict(status="unsupported", detail=str(error), transitions=0, actions=0)
            episode.prepare_ms = None
            observation = None
        reset_ms = ms(reset)
        while not episode.done:
            score_started = perf_counter()
            action = choose(observation, observation.actions, defense_first)
            decision_ms += ms(score_started)
            trajectory.append(dict(observation=asdict(observation), action=action.native()))
            observation = episode.step(action)
        result = episode.result()
        wall = ms(started)
        prepare_ms = episode.prepare_ms
    finally:
        closing = perf_counter()
        episode.close()
        close_ms = ms(closing)
    if game.request("f1_audit") != before:
        raise ValueError("Original native root was mutated")
    memory = game.read_memory(game.engine.proc) if game.read_memory else None
    return dict(id=item["case"]["id"], phase=phase, defense_first=defense_first, episode_ms=wall,
                reset_ms=reset_ms, prepare_ms=prepare_ms, close_ms=close_ms,
                decision_ms=decision_ms, trajectory=trajectory, terminal=result,
                memory=game.report.get("peak_working_set_bytes"),
                working_set=memory[0] if memory else None)


def semantic(result):
    terminal = {k: v for k, v in result["terminal"].items() if not k.endswith("_ms")}
    return result["trajectory"], terminal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--rounds", type=int, default=32)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 32:
        parser.error("rounds must be in [1, 32]")
    output = args.output.resolve()
    output.mkdir(parents=True)
    versions = s3a.solver_binding(output, s3a.FIXED, ROOT / "logs/m1-e3f/release")
    selected = list(cases())
    data = dict(versions=versions, inputs=selected, lifecycle=[], rows=[], batches={})
    rows = data["rows"]
    for phase in ("cold", "same", "mixed"):
        start = perf_counter()
        offset = len(rows)
        if phase == "cold":
            for item in selected:
                with worker(output, item, versions, data["lifecycle"]) as (game, _):
                    rows.append(execute(game, item, False, phase))
        elif phase == "same":
            item = selected[0]
            with worker(output, item, versions, data["lifecycle"]) as (game, _):
                for index in range(args.rounds):
                    rows.append(execute(game, item, index % 3 == 1, phase))
        else:
            with ExitStack() as stack:
                games = [stack.enter_context(worker(output, item, versions, data["lifecycle"]))[0]
                         for item in selected]
                for index in range(args.rounds * len(selected)):
                    slot = index % len(selected)
                    rows.append(execute(games[slot], selected[slot], index // len(selected) % 3 == 1, phase))
        data["batches"][phase] = dict(wall_ms=ms(start), n=len(rows)-offset,
                                     stops=Counter(r["terminal"]["status"] for r in rows[offset:]))
        bank.atomic(output / "results.json", data)

    seen = {}
    for row in rows:
        key = row["id"], row["defense_first"]
        value = semantic(row)
        if seen.setdefault(key, value) != value:
            raise ValueError(f"Determinism failure for {key}")


if __name__ == "__main__":
    main()
