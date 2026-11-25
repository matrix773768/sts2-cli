"""Bounded paired search diagnostics on six frozen development worlds."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
from time import perf_counter

import reference as ref


def idle():
    path = ref.ROOT / "logs/inf1/queue.sqlite"
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("SELECT 1 FROM runs WHERE ended IS NULL").fetchone():
            raise RuntimeError("INF1 has an active run")


def launch(build, out, mode, tier, env, request, route):
    started = perf_counter()
    result = out / f"{mode}.json"
    with (out / f"{mode}.log").open("wb") as log:
        subprocess.run([str(ref.RUNTIME), build["dll"], "--hk1a", mode, str(request),
                        str(result), str(tier), str(route)], cwd=build["tree"],
                       stdout=log, stderr=subprocess.STDOUT, check=True, env=env, timeout=50)
    return ref.old.read(result) | {"end_to_end_seconds": perf_counter() - started}


def main(args):
    idle()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    build = ref.old.read(args.build)
    if ref.checksum(Path(build["dll"])) != build["overlay_sha256"]:
        raise ValueError("Performance Harness identity changed")
    if ref.checksum(Path(build["solver_path"])) != build["solver_sha256"]:
        raise ValueError("Performance Solver identity changed")
    pilot = ref.ROOT / "logs/m1-dc3a-frozen/pilot.json"
    worlds = ref.select_worlds(ref.old.read(pilot), True)
    prior = ref.extension_source(ref.PILOT_LEDGER, ref.old.read(pilot)["worlds"], ref.BUILD, pilot)
    ref.old.write_json(out / "worlds.json", dict(manifest=ref.checksum(pilot), worlds=worlds))
    host = ref.old.Host(out, ref.old.BUILD, ref.old.config() | {"workers": 1})
    if args.legacy:
        for world in worlds:
            idle()
            start = perf_counter()
            row = ref.old.solve(host, world, ((2048, 10),))
            if row["root"] != prior[world["id"]]["root"]:
                raise ValueError("Old solver root differs from original pilot")
            ref.old.write_json(out / f"{world['id']}.json",
                               row | {"end_to_end_seconds": perf_counter() - start})
            print(world["spec"]["encounter"], row["tiers"][0]["search_status"],
                  row["reference"]["net"] if row["reference"] else None, flush=True)
        return
    arms = [("A", 1, 32, 150000), ("B", 1, 64, 150000),
            ("C", 4, 64, 150000), ("D", 8, 64, 150000)]
    if args.nodes:
        worlds = [worlds[0], worlds[-1]]
        arms = [("N1", 1, 64, args.nodes), ("N4", 4, 64, args.nodes)]
    if args.no_tier:
        worlds = [worlds[0], worlds[-1]]
        arms = [("J1", 1, 64, 150000), ("J4", 4, 64, 150000)]
    for position, world in enumerate(worlds):
        base = out / world["id"]
        base.mkdir()
        with ref.old.opened(host, world) as (_, public, native, audit, init):
            if ref.old.digest([public, native, audit]) != prior[world["id"]]["root"]:
                raise ValueError("Legacy performance root differs from original pilot")
        request = base / "request.json"
        ref.old.write_json(request, {"spec": world["spec"]})
        ref.old.write_json(base / "legacy.json", {"native": native, "init_seconds": init})
        for arm, dop, branches, nodes in arms[position % len(arms):] + arms[:position % len(arms)]:
            idle()
            directory = base / arm
            directory.mkdir()
            env = os.environ | dict(HKPERF_DOP=str(dop), HKPERF_BRANCHES=str(branches),
                                    HKPERF_NODES=str(nodes), OFFLINE_HARNESS_STREAM_DIAGNOSTICS="1")
            env.pop("DOTNET_PROCESSOR_COUNT", None)
            if args.no_tier:
                env["DOTNET_TieredCompilation"] = "0"
            route_file = directory / "route.json"
            search = launch(build, directory, "solve", 10000, env, request, route_file)
            actual = search["identity"]
            deck = [{k.lower(): v for k, v in c.items()} for c in actual["deck"]]
            normalized = actual | {"deck": deck}
            if any(normalized[k] != native[k] for k in (*ref.FIELDS, "continuation")):
                raise ValueError("Search root differs from original pilot")
            result = dict(arm=arm, dop=dop, branches=branches, nodes=nodes, init=search["init"],
                          search=search["search"], policy=search["policy"], perf=search["perf"],
                          seconds=search["WallSeconds"], end_to_end_seconds=search["end_to_end_seconds"])
            if search["route"]:
                ref.old.write_json(route_file, search["route"])
                replay = launch(build, directory, "replay", 10000, env, request, route_file)
                if replay["identity"] != actual:
                    raise ValueError("Cold replay root differs")
                result["native"] = replay["status"]
                result["replay_ms"] = replay["replayMs"]
                result["end_to_end_seconds"] += replay["end_to_end_seconds"]
                if replay["status"] == "native_win":
                    result["net"] = replay["initial"]["Hp"] - replay["lockedHp"]
            ref.old.write_json(directory / "metrics.json", result)
            print(world["spec"]["encounter"], arm, result["search"]["totalTransitions"],
                  round(result["seconds"], 2), result.get("net"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--build", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--nodes", type=int)
    mode.add_argument("--no-tier", action="store_true")
    mode.add_argument("--legacy", action="store_true")
    main(parser.parse_args())
