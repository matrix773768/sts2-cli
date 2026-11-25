"""Run the independent HotKernel DC3A reference on a frozen development queue."""
import argparse
from collections import Counter
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from time import perf_counter

from hk1a_build import ROOT, checksum

old_spec = importlib.util.spec_from_file_location(
    "dc3a_legacy", ROOT / "experiments/m1-dc3a/reference.py")
old = importlib.util.module_from_spec(old_spec)
old_spec.loader.exec_module(old)

TIERS = (100, 500, 2000, 10000)
FIELDS = ("seed", "character", "ascension", "should_save", "replay_writer_enabled",
          "visited_map_nodes", "run_rng", "player_rng", "deck",
          "hand", "draw", "discard", "exhaust", "act", "act_variant", "act_boss")
BUILD = ROOT / "logs/hk1a-build/build.json"
RUNTIME = ROOT / "logs/m0-v5/dotnet9/dotnet.exe"


def select_worlds(source, sample):
    worlds = source["worlds"]
    if not sample:
        return worlds
    chosen = {}
    for world in worlds:
        chosen.setdefault((world["source"], world["spec"]["max_hp"]), world)
    return list(chosen.values())


def invoke(build, directory, mode, tier, spec, route=None):
    path = directory / f"{mode}-{tier}.json"
    request = directory / "request.json"
    old.write_json(request, {"spec": spec})
    route_path = directory / f"route-{tier}.json"
    if route is not None:
        old.write_json(route_path, route)
    args = [str(RUNTIME), build["dll"], "--hk1a", mode, str(request), str(path),
            str(tier), str(route_path)]
    started = perf_counter()
    with (directory / f"{mode}-{tier}.log").open("wb") as log:
        subprocess.run(args, cwd=build["tree"], stdout=log, stderr=subprocess.STDOUT,
                       env=os.environ | {"DOTNET_PROCESSOR_COUNT": "1"}, check=True,
                       timeout=45 + (tier / 1000 if mode == "solve" else 75))
    return old.read(path) | {"process_seconds": perf_counter() - started}


def solve_world(host, build, directory, world, tiers):
    with old.opened(host, world) as (_, public, native, audit, init):
        root = old.digest([public, native, audit])
    row = dict(world=world, root=root, legacy_init_seconds=init, tiers=[],
               reference=None, solver=build["version"], information="offline_oracle_full_rng")
    old.write_json(directory / "legacy-private.json", {"public": public, "native": native, "audit": audit})
    for tier in tiers:
        result = {"budget_ms": tier}
        try:
            search = invoke(build, directory, "solve", tier, world["spec"])
            candidate = search["identity"]
            candidate["deck"] = [{key.lower(): value for key, value in card.items()}
                                 for card in candidate["deck"]]
            different = [key for key in FIELDS if candidate[key] != native[key]]
            def fields(stamp):
                return [part.partition("=") for part in stamp.split(";")]
            if fields(candidate["continuation"]) != fields(native["continuation"]):
                different.append("native_continuation")
            result.update(boundary=search["boundary"], search=search["search"],
                          init_ms=search["init"], search_seconds=search["WallSeconds"],
                          mismatched_fields=different)
            if different:
                result["status"] = "root_mismatch"
            elif search["route"] is None:
                result["status"] = "no_win_route"
            else:
                replay = invoke(build, directory, "replay", tier, world["spec"], search["route"])
                if replay["identity"] != old.read(directory / f"solve-{tier}.json")["identity"]:
                    result["status"] = "cold_root_mismatch"
                else:
                    result["status"] = replay["status"]
                    result["replay_ms"] = replay["replayMs"]
                    if replay["status"] == "native_win":
                        loss = world["spec"]["hp"] - replay["lockedHp"]
                        if row["reference"] is None or loss < row["reference"]["net"]:
                            row["reference"] = dict(net=loss, budget_ms=tier, end_hp=replay["lockedHp"],
                                                    post_combat_hp=replay["hp"], max_hp=replay["maxHp"],
                                                    length=len(replay["frames"]))
        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
        except subprocess.CalledProcessError as error:
            result.update(status="worker_error", exit_code=error.returncode)
        row["tiers"].append(result | {"incumbent": row["reference"]})
    historical = ROOT / "logs/m1-dc3a-smoke-model" / f"{world['id']}.json"
    if historical.is_file() and any(r.get("mismatched_fields") == [] for r in row["tiers"]):
        model = old.read(historical)
        if model.get("attested_root") == root:
            row["historical_model"] = {key: model.get(key) for key in ("status", "terminal", "attested_root")}
    return row


def run(args):
    data = old.read(args.manifest)
    kind = data["kind"]
    expected = {"dc3a-pilot": 24, "dc3a-formal": 192}
    if kind not in expected or len(data["worlds"]) != expected[kind]:
        raise ValueError("Expected a frozen DC3A development queue")
    frozen = ROOT / "logs/m1-dc3a-frozen" / (kind.removeprefix("dc3a-") + ".json")
    if checksum(args.manifest) != checksum(frozen):
        raise ValueError("Queue identity differs from the original")
    build = old.read(args.build)
    for path, sha in (build["artifacts"] | build["adapter"]).items():
        if checksum(Path(path)) != sha:
            raise ValueError(f"Changed runtime artifact {path}")
    tiers = (2000,) if args.sample else TIERS
    if kind == "dc3a-formal":
        if args.sample or not args.budget_file:
            raise ValueError("Formal queue requires the completed HotKernel pilot budget")
        pick = old.read(args.budget_file)
        tiers = tuple(pick["tiers"])
        if (not tiers or tiers != TIERS[:len(tiers)] or pick["build"] != checksum(args.build)
            or pick["pilot_manifest"] != checksum(frozen.with_name("pilot.json"))):
            raise ValueError("Budget does not match this build")
    queue = select_worlds(data, args.sample)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "reference.sqlite"
    identity = old.digest([checksum(args.manifest), tiers, args.sample, checksum(args.build),
                           checksum(Path(__file__)), checksum(old.BUILD / "build.json")])
    with closing(sqlite3.connect(db_path)) as db:
        db.executescript("CREATE TABLE IF NOT EXISTS contract(id TEXT PRIMARY KEY);"
                         "CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY,payload TEXT NOT NULL);")
        with db:
            previous = db.execute("SELECT id FROM contract").fetchone()
            if previous and previous[0] != identity:
                raise ValueError("Reference identity changed")
            db.execute("INSERT OR IGNORE INTO contract VALUES (?)", (identity,))
        host = old.Host(out, old.BUILD, old.config() | {"workers": 1})
        done = {key for key, in db.execute("SELECT id FROM results")}
        for world in queue:
            if world["id"] in done:
                continue
            stop = os.getenv("INF1_STOP")
            if stop and Path(stop).exists():
                return 75
            directory = out / world["id"]
            directory.mkdir(exist_ok=True)
            row = solve_world(host, build, directory, world, tiers)
            if stop and Path(stop).exists():
                return 75
            with db:
                db.execute("INSERT INTO results VALUES (?,?)", (world["id"], json.dumps(row)))
            done.add(world["id"])
            print(world["id"][:8], [tier["status"] for tier in row["tiers"]], flush=True)
            if "INF1_PROGRESS" in os.environ:
                old.progress(len(done), len(queue), db_path)
        rows = [json.loads(payload) for payload, in db.execute("SELECT payload FROM results")]
    milestones = [{r["world"]["id"]: r["tiers"][i]["incumbent"]["net"] for r in rows
                   if r["tiers"][i]["incumbent"]} for i in range(len(tiers))]
    if kind == "dc3a-pilot" and not args.sample and milestones[-1]:
        final = milestones[-1]
        chosen = next(i for i, wins in enumerate(milestones) if wins.keys() == final.keys()
                      and sum(wins.values()) - sum(final.values()) <= 2 * len(final))
        old.frozen(out / "budget.json", {"tiers": list(tiers[:chosen+1]), "build": checksum(args.build),
                                         "pilot_manifest": checksum(args.manifest)})
    old.write_json(out / "summary.json", {"worlds": len(rows), "wins": len(milestones[-1]),
        "tiers": tiers, "statuses": dict(Counter(t["status"] for r in rows for t in r["tiers"]))})
    return 0 if args.sample or milestones[-1] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--build", type=Path, default=BUILD)
    parser.add_argument("--budget-file", type=Path)
    parser.add_argument("--sample", action="store_true")
    raise SystemExit(run(parser.parse_args()))
