"""Freeze and replay PRE1 training prefixes, then measure turn graphs inside the host."""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import sqlite3
import sys
from threading import local
from time import perf_counter

from build import HERE, ROOT, digest
sys.path.insert(0, str(HERE.parent / "m1-pre0b"))


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def stamp(value):
    return sha256(encode(value)).hexdigest()


def config():
    return json.loads((HERE / "config.json").read_bytes())


def open_source(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def payload(data, expected):
    raw = gzip.decompress(data)
    if sha256(raw).hexdigest() != expected:
        raise ValueError("PRE1 trajectory payload hash mismatch")
    return json.loads(raw)


def freeze(output, cfg):
    generator = random.Random(cfg["sample_seed"])
    output.parent.mkdir(parents=True, exist_ok=True)
    sources, roots = {}, []
    for source, quota in cfg["sources"].items():
        path = ROOT / f"logs/m1-pre1-data-{source}/dataset.sqlite"
        file_hash = digest(path)
        with closing(open_source(path)) as db:
            manifest = db.execute("SELECT sha, json FROM manifest").fetchone()
            if sha256(manifest[1]).hexdigest() != manifest[0]:
                raise ValueError(f"Changed source manifest for {source}")
            ids = db.execute("SELECT ordinal FROM trajectories WHERE split='train' AND complete=1 ORDER BY ordinal").fetchall()
            generator.shuffle(ids)
            groups = {}
            # Candidate trajectories are sampled before their steps are opened.
            for ordinal, in ids[:quota * 3]:
                record_id, expected, data, recipe = db.execute("""
                    SELECT t.id, t.sha, t.payload, p.recipe FROM trajectories t
                    LEFT JOIN private_tasks p USING(id) WHERE ordinal=?
                """, (ordinal,)).fetchone()
                row = payload(data, expected)
                steps = row["steps"]
                starts = [i for i, step in enumerate(steps)
                          if i == 0 or step["observation"]["turn"] != steps[i-1]["observation"]["turn"]]
                phase = "turn_start" if generator.random() < .75 else "intermediate"
                positions = starts if phase == "turn_start" else list(set(range(len(steps))) - set(starts))
                if not positions:
                    positions, phase = starts, "turn_start"
                i = generator.choice(sorted(positions))
                obs = steps[i]["observation"]
                bucket = min(obs["turn"], 4)
                root = dict(source=source, row_id=record_id, ordinal=ordinal, prefix=i, payload_sha256=expected,
                            recipe_sha256=None if recipe is None else sha256(recipe).hexdigest(),
                            observation_sha256=stamp(obs), turn=obs["turn"], energy=obs["energy"],
                            hand=len(obs["hand"]), hp=obs["hp"], act=row["root"]["act"], room=row["room"],
                            encounter=row["root"]["encounter"], start=phase, phase=obs["decision"]["phase"],
                            cards=[c["id"] for c in obs["hand"]], actions=len(obs["actions"]))
                groups.setdefault((root["act"], bucket, root["room"]), deque()).append(root)
            positions = list(groups)
            generator.shuffle(positions)
            accepted = 0
            while positions and accepted < quota:
                for key in positions[:]:
                    roots.append(groups[key].popleft())
                    accepted += 1
                    if not groups[key]:
                        positions.remove(key)
                    if accepted == quota:
                        break
            if accepted != quota or digest(path) != file_hash:
                raise ValueError(f"Sampling quota or source stability failure for {source}")
            sources[source] = dict(path=path.relative_to(ROOT).as_posix(), manifest_sha256=manifest[0],
                                   database_sha256=file_hash, complete_train=len(ids))
    generator.shuffle(roots)
    for index, root in enumerate(roots):
        root["index"] = index
    result = dict(schema=1, seed=cfg["sample_seed"], sources=sources, roots=roots,
                  method="one decision per complete train trajectory; round-robin act/turn/room within source")
    with output.open("xb") as stream:
        stream.write(encode(result) + b"\n")
    return result


class ReconstructionError(RuntimeError):
    pass


class Host:
    def __init__(self, output, build):
        self.output, self.build = output, build
        self.identity = json.loads((build / "build.json").read_bytes())
        for name, value in self.identity["artifacts"].items():
            if digest(build / name) != value:
                raise ValueError(f"Build artifact changed: {name}")
        sys.path.insert(0, str(ROOT / "python"))
        import engine_client
        from transport import buffered_client
        self.client = buffered_client(engine_client.EngineClient, engine_client.EngineCancelled)
        os.environ.update(
            I1_SOLVER=str(build / "solver-bin/CombatSolver.dll"), I1_RITSU=self.identity["ritsu"],
            STS2_DOTNET_VERSION="9.0.7", I1_LOG=".",
        )
        os.environ.setdefault("STS2_DOTNET", str(ROOT / "logs/m1-review-dotnet/dotnet.exe"))
        command = engine_client.headless_command()
        engine_client.headless_command = lambda: [*command[:-1],
            str(build / "host/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll")]
        self.local = local()
        self.lanes = []

    def lane(self):
        if not hasattr(self.local, "lane"):
            self.local.lane = Lane(self)
            self.lanes.append(self.local.lane)
        return self.local.lane

    def close(self):
        for lane in self.lanes:
            lane.close()


class Lane:
    def __init__(self, host):
        self.host = host
        self.client = None
        self.count = 0

    def launch(self):
        if self.client is None:
            self.client = self.host.client(log_root=self.host.output / "engine")
            self.count = 0
            identity = self.request("i1_s3a_identity")
            if identity["sha256"] != self.host.identity["artifacts"]["solver-bin/CombatSolver.dll"]:
                raise ValueError("Unexpected loaded SV1 Solver")
        self.count += 1

    def request(self, command, **args):
        result = self.client.send(dict(cmd=command, **args))
        if result["type"] == "error":
            # Diagnostic and full stack trace are also preserved in the isolated host log.
            raise RuntimeError(result.get("message") or result.get("error") or result["type"])
        return result

    def reset(self):
        for command in ("i1_n2_close", "i1_release", "f1_3c_release", "pre0_abandon"):
            self.request(command)
        if self.request("b1a_profile")["value"] != self.request("b1b_initial_profile")["value"]:
            raise ValueError("Resident host profile changed")

    def close(self):
        if self.client is not None:
            try:
                self.client.close()
            finally:
                self.client = None


def project(wire, shape):
    """Compare v3 wire observations using the recorded public field set and null defaults."""
    if isinstance(shape, dict):
        if not isinstance(wire, dict):
            return wire
        return {key: project(wire.get(key), value) for key, value in shape.items()}
    if isinstance(shape, list) and isinstance(wire, list) and len(wire) == len(shape):
        return [project(item, expected) for item, expected in zip(wire, shape)]
    return wire


def reconstruct(lane, recipe, steps, position, fixture=None):
    begin = perf_counter()
    result = lane.request("pre0_start", spec=recipe, cap=max(128, position + 1),
                          **({} if fixture is None else {"sv1_fixture": fixture}))
    state = result.get("episode")
    root_ms = (perf_counter() - begin) * 1000
    begin = perf_counter()
    for index in range(position + 1):
        if state is None or state["status"] != "active" or state["actions"] != index:
            raise ReconstructionError(f"Decision {index} unavailable: {state and state['status']}")
        if steps is not None:
            expected = steps[index]["observation"]
            actual = project(state["observation"], expected)
            changed = [key for key, value in expected.items() if actual.get(key) != value]
            if changed:
                raise ReconstructionError(f"Decision {index} replay mismatch: {', '.join(changed)}")
        if index < position:
            step = steps[index]
            action = step["action"]
            if step["position"] != index or not step["advanced"] or expected["actions"][action["index"]] != action:
                raise ReconstructionError(f"Invalid historical action at {index}")
            state = lane.request("i1_n2_step", position=index, index=action["index"])["episode"]
    return state, dict(root_ms=root_ms, prefix_ms=(perf_counter() - begin) * 1000)


def search(lane, mode, settings, **flags):
    begin = perf_counter()
    result = lane.request("i1_sv1_graph", mode=mode, **settings, **flags)
    if result["type"] != "sv1_graph":
        raise ValueError("Unexpected graph response")
    result["rpc_ms"] = (perf_counter() - begin) * 1000
    result["wire_overhead_ms"] = max(0, result["rpc_ms"] - result["timing"]["search_ms"])
    return result


def read_history(root, sources):
    with closing(open_source(ROOT / sources[root["source"]]["path"])) as db:
        row = db.execute("""
            SELECT t.sha, t.payload, p.recipe FROM trajectories t LEFT JOIN private_tasks p USING(id)
            WHERE t.ordinal=? AND t.id=? AND t.split='train' AND t.complete=1
        """, (root["ordinal"], root["row_id"])).fetchone()
    if not row or row[0] != root["payload_sha256"] or row[2] is None:
        raise ReconstructionError("Frozen record or private recipe unavailable")
    data = payload(row[1], row[0])
    if sha256(row[2]).hexdigest() != root["recipe_sha256"]:
        raise ReconstructionError("Frozen recipe hash mismatch")
    if stamp(data["steps"][root["prefix"]]["observation"]) != root["observation_sha256"]:
        raise ReconstructionError("Frozen observation hash mismatch")
    return json.loads(row[2]), data["steps"]


def experiment(output, manifest, build, cfg, workers, max_new=None):
    output.mkdir(parents=True, exist_ok=True)
    for name, source in manifest["sources"].items():
        if digest(ROOT / source["path"]) != source["database_sha256"]:
            raise ValueError(f"Frozen source database changed: {name}")
    host = Host(output, build)
    contract = dict(manifest=stamp(manifest), config=cfg, workers=workers, build=host.identity,
                    experiment_sources={name: digest(HERE / name) for name in ("campaign.py", "build.py", "TurnGraph.cs", "SearchProbe.cs")})
    contract_sha = stamp(contract)
    # A separate SQLite write transaction excludes concurrent drivers while allowing incremental commits.
    with closing(sqlite3.connect(output / "writer.sqlite", timeout=0)) as lock:
        lock.execute("BEGIN EXCLUSIVE")
        with closing(sqlite3.connect(output / "results.sqlite")) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS contract(sha TEXT PRIMARY KEY, json BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS results(idx INTEGER PRIMARY KEY, status TEXT, sha TEXT, payload BLOB);
                CREATE TABLE IF NOT EXISTS sessions(started TEXT DEFAULT CURRENT_TIMESTAMP, completed INTEGER, wall_s REAL);
            """)
            stored = db.execute("SELECT sha FROM contract").fetchone()
            if stored and stored[0] != contract_sha:
                raise ValueError("Resume identity changed; use a separate output directory")
            with db:
                db.execute("INSERT OR IGNORE INTO contract VALUES (?,?)", (contract_sha, encode(contract)))
                session = db.execute("INSERT INTO sessions(completed, wall_s) VALUES (0, 0)").lastrowid
            done = {row[0] for row in db.execute("SELECT idx FROM results")}
            todo = [root for root in manifest["roots"] if root["index"] not in done][:max_new]
            started = perf_counter()

            def attempt(root):
                lane = host.lane()
                record = dict(root=root, status="error", graphs={})
                begin = perf_counter()
                try:
                    recipe, steps = read_history(root, manifest["sources"])
                    lane.launch()
                    record["log"] = str(lane.client.log_dir.relative_to(output))
                    _, record["rebuild"] = reconstruct(lane, recipe, steps, root["prefix"])
                    record["status"] = "searched"
                    for mode in ("k0", "k1"):
                        record["graphs"][mode] = search(lane, mode, cfg["settings"])
                    if root["index"] % cfg["tree_every"] == 0:
                        record["graphs"]["tree"] = search(lane, "tree", cfg["tree_settings"])
                    if lane.count >= cfg["recycle_roots"]:
                        lane.close()
                    else:
                        lane.reset()
                except (ReconstructionError, ValueError, RuntimeError, KeyError, TimeoutError, OSError) as error:
                    if len(record["graphs"]) < 2:
                        record["status"] = "search_error" if record["status"] == "searched" else "reconstruction_failed"
                    record["error"] = f"{type(error).__name__}: {error}"
                    lane.close()
                record["wall_ms"] = (perf_counter() - begin) * 1000
                return record

            try:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for offset in range(0, len(todo), max(1, workers * 4)):
                        batch = todo[offset:offset + workers * 4]
                        for row_number, result in enumerate(pool.map(attempt, batch), offset + 1):
                            index = result["root"]["index"]
                            raw = encode(result)
                            with db:
                                db.execute("INSERT INTO results VALUES (?,?,?,?)",
                                           (index, result["status"], sha256(raw).hexdigest(),
                                            gzip.compress(raw, compresslevel=3, mtime=0)))
                                db.execute("UPDATE sessions SET completed=?, wall_s=? WHERE rowid=?",
                                           (row_number, perf_counter() - started, session))
                            if row_number % 64 == 0:
                                print(f"committed {len(done) + row_number}/{len(manifest['roots'])}", flush=True)
            finally:
                host.close()


def main():
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest="command", required=True)
    freeze_args = command.add_parser("freeze")
    freeze_args.add_argument("manifest", type=Path)
    run_args = command.add_parser("run")
    run_args.add_argument("manifest", type=Path)
    run_args.add_argument("output", type=Path)
    run_args.add_argument("--build", type=Path, required=True)
    run_args.add_argument("--workers", type=int, default=4)
    run_args.add_argument("--max-new", type=int)
    run_args.add_argument("--transitions", type=int)
    args = parser.parse_args()
    cfg = config()
    if args.command == "freeze":
        manifest = freeze(args.manifest, cfg)
        print(f"{len(manifest['roots'])} frozen roots, manifest SHA256 {stamp(manifest)}")
    else:
        if args.transitions is not None:
            cfg["settings"]["transitions"] = args.transitions
        experiment(args.output.resolve(), json.loads(args.manifest.read_bytes()), args.build.resolve(),
                   cfg, args.workers, args.max_new)


if __name__ == "__main__":
    main()
