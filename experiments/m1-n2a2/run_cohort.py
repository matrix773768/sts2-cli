"""Run the frozen dual-policy, dual-budget development cohort."""
import argparse
from contextlib import ExitStack
import hashlib
from pathlib import Path
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-n2a1"))
from interaction import Episode
import qualify_interaction as interaction
from design import generate, stamp

base = interaction.base
base.s3a.HOST = "m1-n2a2-build"


class BudgetEpisode(Episode):
    def reset(self):
        self.audit_actions = []
        self.audit_stamps = []
        self.state = None
        reply = self.worker.request("i1_n2_reset", arm="A", cap=self.worker.n2a2_cap,
                                    potions=False, rejected=[])
        self.state = reply.get("episode", reply)
        self.prepare_ms = reply.get("root_prepare_ms")
        return self.observation


def execute(game, item, policy, cap, phase):
    game.n2a2_cap = cap
    try:
        row = interaction.execute(game, item, policy, phase)
    except base.bank.f1.i2.StopRun as error:
        row = dict(id=item["case"]["id"], phase=phase, defense_first=policy, trajectory=[],
                   terminal=dict(status="execution_error", detail=str(error)))
    return row | {"cap": cap, "evidence": "prediction_only"}


def verify_budgets(rows):
    prior = {}
    for row in rows:
        prior[row["id"], row["defense_first"], row["cap"]] = row
    for (id_, policy, cap), first in prior.items():
        if cap != 48 or (id_, policy, 96) not in prior:
            continue
        extended = prior[id_, policy, 96]
        if first["terminal"]["status"] == "execution_error" or extended["terminal"]["status"] == "execution_error":
            continue
        steps = len(first["trajectory"])
        if first["trajectory"] != extended["trajectory"][:steps]:
            raise ValueError(f"Fixed prefix changed for {id_}")
        if first["terminal"].get("audit_stamps") != extended["terminal"].get("audit_stamps", [])[:steps]:
            raise ValueError(f"Fixed continuation changed for {id_}")
        if first["terminal"]["status"] != "truncated" and base.semantic(first) != base.semantic(extended):
            raise ValueError(f"Terminal result changed for {id_}")


def one_batch(output, items, versions, result, kind):
    started = perf_counter()
    rows = []
    lifecycle = []
    roots = []
    with ExitStack() as stack:
        games = {}
        for item in items:
            case = item["case"]
            init = perf_counter()
            try:
                game, _ = stack.enter_context(base.worker(output, item, versions, lifecycle))
            except base.bank.f1.i2.StopRun as error:
                roots.append(dict(id=case["id"], status="build_error", detail=str(error), ms=base.ms(init)))
                rows.extend(dict(id=case["id"], cap=cap, defense_first=policy, phase=kind,
                                 trajectory=[], evidence="prediction_only",
                                 terminal=dict(status="build_error", detail=str(error)))
                            for cap in (48, 96) for policy in (False, True))
                continue
            roots.append(dict(id=case["id"], status="native_built", ms=base.ms(init),
                              root_sha256=lifecycle[-1]["root_sha256"]))
            games[case["id"]] = game
            rows.append(execute(game, item, False, 48, "first"))
        warm = perf_counter()
        for cap, policy in ((48, True), (96, False), (96, True)):
            for item in items:
                if item["case"]["id"] in games:
                    rows.append(execute(games[item["case"]["id"]], item, policy, cap, kind))
        primary_warm_ms = base.ms(warm)
        repeated = []
        warm = perf_counter()
        if kind == "pool":
            for _ in range(2):
                for item in items:
                    if item["case"]["id"] in games:
                        repeated.append(execute(games[item["case"]["id"]], item, False, 96, "repeat_pool"))
            item = items[0]
            game = games.get(item["case"]["id"])
            same_started = perf_counter()
            same = [execute(game, item, bool(i % 2), 96, "repeat_same") for i in range(16)] if game else []
            same_ms = base.ms(same_started)
        else:
            same, same_ms = [], 0
        repeats_ms = base.ms(warm) - same_ms
        close = perf_counter()
    verify_budgets(rows)
    known = {(r["id"], r["defense_first"], r["cap"]): r for r in rows}
    for row in repeated + same:
        expected = known[row["id"], row["defense_first"], row["cap"]]
        if base.semantic(row) != base.semantic(expected):
            raise ValueError(f"Resident replay differs for {row['id']}")
    result["batches"].append(dict(kind=kind, n=len(items), wall_ms=base.ms(started),
                                  primary_warm_ms=primary_warm_ms, close_ms=base.ms(close),
                                  repeats_ms=repeats_ms, same_ms=same_ms, roots=roots,
                                  lifecycle=lifecycle, rows=rows, repeats=repeated, same=same))
    base.bank.atomic(output / "results.json", result)
    print(kind, len(items), len(result["batches"]), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    plan = base.bank.read(HERE / "manifest.json")
    if list(generate()) != plan["cases"]:
        raise ValueError("Manifest differs from frozen generator")
    versions = base.s3a.solver_binding(output, base.s3a.FIXED, base.ROOT / "logs/m1-e3f/release")
    base.Episode = BudgetEpisode
    base.choose = interaction.choose
    sources = [HERE / "design.py", Path(__file__), HERE.parent / "m1-n2a1/qualify_interaction.py",
               HERE.parent / "m1-n2a/environment.py", HERE.parent / "m1-n2a1/interaction.py"]
    result = dict(manifest_sha256=stamp(plan), versions=versions, batches=[], policies=[
        "n2a1 non-defense first", "n2a1 defense first"],
        source_sha256={str(path.relative_to(base.ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources})
    cases = plan["cases"]
    # Interleave encounter groups so the resident pool includes distinct roots and roles.
    ordered = [cases[e * 12 + i] for i in range(12) for e in range(8)]
    one_batch(output, ordered[:8], versions, result, "pool")
    for start in range(8, len(ordered), 8):
        one_batch(output, ordered[start:start + 8], versions, result, "rotation")


if __name__ == "__main__":
    main()
