"""Produce durable prediction-only Ironclad trajectories using the frozen v4 policy."""
from time import monotonic, perf_counter, time_ns
START = perf_counter()

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import ExitStack, closing, nullcontext
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import runpy
import sqlite3

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent / 'm1-pre0'))
from dataset import digest, encode

HERE = Path(__file__).resolve().parent
p0 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii-p0/run.py"))
torch, v4, targets = (p0[k] for k in ("torch", "v4", "targets"))
from batching import Inference
from transport import buffered_client
from nosl_model import CATALOG

BANK = targets.BANK
CONTRACT = "sts2.m1-pre0.prediction-only.v1"


def root(catalog, config, ordinal):
    rng = random.Random(int(digest([config["seed"], ordinal]), 16))
    role, = [role for role in catalog["characters"] if role["name"] == "Ironclad"]
    acts = [(a["act"], a["variant"], e) for a in catalog["acts"] if a["act"] in (1, 2, 3)
            for e in a["encounters"] if e["room"] in config["rooms"]]
    act, variant, encounter = rng.choice(acts)
    pool = [c for c in role["cards"] if c["id"] not in config["exclude"]]
    cards = rng.choices(pool, k=rng.randint(*config["deck_length"]))
    hp = config["hp"][ordinal % len(config["hp"])]
    family = digest(sorted(c["id"] for c in cards))
    bucket = int(family[:8], 16) % 100
    split = "train" if bucket < 80 else "validation" if bucket < 90 else "evaluation"
    spec = dict(schema=3, character="Ironclad", ascension=0, act=act, act_variant=variant,
                encounter=encounter["id"], seed=digest([config["version"], config["seed"], ordinal])[:16].upper(),
                hp=hp, max_hp=max(hp, role["max_hp"]), relics=[], potions=[],
                deck=[dict(id=c["id"], upgrade=int(c["upgradable"] and rng.random() < config["upgrade_rate"]))
                      for c in cards])
    return spec, split, family, encounter["room"]


def bind_host(args):
    versions = p0["accept"]["bind"](args.output, p0["SOLVER"])
    if args.host is None:
        return versions
    host = args.host.resolve()
    identity = json.loads((host / "build.json").read_bytes())
    binary = host / "Headless/bin/Debug/net9.0"
    hashes = {name: sha256((binary / name).read_bytes()).hexdigest()
              for name in ("OfflineSearchHarness.dll", "GodotSharp.dll")}
    if (identity["version"] not in ("PRE0-host.v1", "PRE0-host.v2", "PRE0B-host.v1", "PRE0B-host.v2")
            or any(value != identity["artifacts"][name]["sha256"] for name, value in hashes.items())):
        raise ValueError("Unexpected PRE0 host identity")
    client = BANK.f1.i2.engine_client
    command = client.headless_command()
    image = binary / "OfflineSearchHarness.dll"
    client.headless_command = lambda: [*command[:-1], str(image)]
    return versions | dict(combat_host=identity["version"], headless_sha256=hashes[image.name],
                           godot_sha256=hashes["GodotSharp.dll"],
                           native_identity=digest([versions["native_identity"], hashes]))


class Lane:
    def __init__(self, output, versions, meter, limit, rss_limit):
        self.output, self.versions, self.meter = output, versions, meter
        self.limit, self.rss_limit = limit, rss_limit
        self.stack = self.game = None
        self.events = []

    def acquire(self):
        if self.game is None:
            begin = perf_counter()
            with ExitStack() as setup:
                game = targets.open_worker(self.output, setup, self.versions)
                pid = game.engine.proc.pid
                self.meter.add(pid)
                self.stack = setup.pop_all()
            self.game = game
            self.event = dict(pid=pid, count=0, startup_s=perf_counter()-begin, started=begin)
            self.events.append(self.event)
        self.event["count"] += 1
        return self.game

    def close(self, reason):
        if self.game is not None:
            proc = self.game.engine.proc
            try:
                self.stack.close()
            finally:
                self.meter.retire(proc.pid)
                self.event.update(lifetime_s=perf_counter()-self.event.pop("started"),
                                  reason=reason, exit_code=proc.returncode)
                self.game = self.stack = None

    def release(self, reusable):
        if not reusable:
            self.close("failed_attempt")
            return
        rss, _ = self.game.read_memory(self.game.engine.proc) or (0, 0)
        self.event.setdefault("first_rss", rss)
        self.event["last_rss"] = rss
        self.event["peak_root_rss"] = max(rss, self.event.get("peak_root_rss", 0))
        if (self.event["count"] >= self.limit or rss >= self.rss_limit
                or self.game.deadline - monotonic() < 30):
            self.close("recycle")
            return
        for command in ("i1_release", "f1_3c_release", "pre0_abandon"):
            self.game.request(command)
        if self.game.request("b1a_profile")["value"] != self.game.request("b1b_initial_profile")["value"]:
            raise ValueError("Resident profile differs from initial profile")


@torch.inference_mode()
def collect(versions, policy, infer, model_hash, config, allowed, job, lane, fast):
    task, ordinal, spec, split, family, room = job
    started = perf_counter()
    rng = random.Random(int(digest([config["policy_seed"], ordinal]), 16))
    history = torch.zeros(targets.base.WIDTH)
    steps, timing = [], Counter()
    state = {}
    visible_cards, unsupported_cards = set(), set()
    status, reason = "error", None
    pid = private_error = None
    try:
        game = lane.acquire()
        pid = game.engine.proc.pid
        timing["startup"] = perf_counter() - started
        tick = perf_counter()
        reset = dict(arm="A", cap=config["action_cap"], potions=False, rejected=[])
        source = None
        if fast and versions["combat_host"] in ("PRE0-host.v2", "PRE0B-host.v1", "PRE0B-host.v2"):
            reply = game.request("pre0_start", spec=spec, cap=config["action_cap"])
            if "episode" not in reply:
                raise ValueError(f"Unexpected root phase: {reply.get('decision', reply.get('type'))}")
            state = reply["episode"]
            timing.update({f"host_{k}": value / 1000 for k, value in game.phase_ms.items()})
        else:
            if fast:
                game.request("synthetic_start", spec=spec)
                timing.update({f"host_{k}": value / 1000 for k, value in game.build_phases.items()})
                game.request("f1_begin")
            else:
                targets.CAPTURE(game, spec)
                source = game.request("f1_audit")
            state = game.request("i1_n2_reset", **reset)["episode"]
        timing["root"] = perf_counter() - tick
        while state["status"] == "active":
            tick = perf_counter()
            obs = targets.project(state["observation"])
            cards = [c for zone in ("hand", "deck", "discard", "exhaust") for c in obs[zone]]
            cards.extend(obs["decision"].get("candidates", ()))
            visible_cards.update(c["id"] for c in cards)
            unsupported_cards = visible_cards - allowed
            if unsupported_cards:
                break
            decision = targets.Decision(obs)
            timing["observation"] += perf_counter() - tick
            tick = perf_counter()
            logits, value, embedding, actions = infer(decision, history)
            logp = logits.log_softmax(0)
            if not torch.isfinite(logp).all() or not torch.isfinite(value):
                raise FloatingPointError("Nonfinite v4 output")
            timing["forward"] += perf_counter() - tick
            tick = perf_counter()
            index = rng.choices(range(len(actions)), weights=logp.exp().tolist(), k=1)[0]
            position = state["actions"]
            step = dict(position=position, observation=obs, action=decision.actions[index],
                        behavior_logp=logp[index].item())
            history = policy.remember(history, embedding, actions[index])
            timing["selection"] += perf_counter() - tick
            tick = perf_counter()
            state = game.request("i1_n2_step", position=position, index=index)["episode"]
            timing["transition_rpc"] += perf_counter() - tick
            timing["host_predict_step"] += game.phase_ms.get("predict_step", 0) / 1000
            step["advanced"] = state["actions"] == position + 1
            steps.append(step)
            if state["status"] == "invalid_action":
                raise ValueError("Solver rejected an action from its own menu")
        tick = perf_counter()
        game.request("i1_n2_close")
        if source is not None and source != game.request("f1_audit"):
            raise ValueError("Prediction changed its source")
        status, reason = state["status"], state.get("detail") or state.get("public_reason")
        if unsupported_cards:
            status, reason = "unsupported", "visible_card_outside_allowlist"
        try:
            lane.release(status in ("predicted_win", "death", "truncated", "unsupported"))
        except (BANK.f1.i2.StopRun, ValueError, RuntimeError, KeyError, OSError, TimeoutError, FloatingPointError) as error:
            lane.event["reset_failure"] = BANK.failure(error)["detail"]
            lane.close("reset_failed")
        timing["close"] = perf_counter() - tick
    except (BANK.f1.i2.StopRun, ValueError, RuntimeError, KeyError, OSError, TimeoutError, FloatingPointError) as error:
        lane.close("exception")
        private_error = BANK.failure(error)
        reason = private_error["status"]
        if "Encounter must be an ordinary member" in private_error["detail"]:
            status, reason = "unsupported", "host_encounter_room_unsupported"
    raw = state.get("result") or {}
    view = state.get("terminal_observation")
    final = {k: view.get(k) for k in ("turn", "hp", "max_hp", "block", "energy", "potions")} if view else None
    if final is not None:
        final["gold"] = raw.get("gold")
    complete = (status in ("predicted_win", "death") and final is not None and bool(steps)
                and state.get("actions") == len(steps)
                and all(row["advanced"] and row["position"] == i for i, row in enumerate(steps)))
    if status in ("predicted_win", "death") and not complete:
        status, reason = "error", "incomplete_terminal_record"
    record = dict(contract=CONTRACT, evidence="prediction_only", id=task, engine=versions,
                  root={k: v for k, v in spec.items() if k != "seed"}, split=split, family=family,
                  source=config["version"], room=room,
                  behavior=dict(model=v4.MODEL, model_sha256=model_hash, mode="sample"),
                  steps=steps, status=status, reason=reason, complete=complete, terminal=final,
                  cumulative_loss=raw.get("cumulative_loss"), solver_gaps=raw.get("gaps", []),
                  visible_cards=sorted(visible_cards), unsupported_cards=sorted(unsupported_cards),
                  mechanism_qualification={card: CATALOG.encode_card_spec(card)["qualification"]
                                           for card in sorted(visible_cards)},
                  length=len(steps))
    return record, dict(pid=pid, seconds=perf_counter()-started, phases=timing, error=private_error)


def disk_bytes(directory):
    total = 0
    for folder, _, files in os.walk(directory):
        for name in files:
            try:
                total += (Path(folder) / name).stat().st_size
            except FileNotFoundError:
                # A native worker can retire one of its temporary files during sampling.
                continue
    return total


def produce(args):
    args.output.mkdir(parents=True, exist_ok=True)
    if args.workers < 1 or args.batch < 1 or args.seconds <= 0 or args.count < 1 or args.disk_mib < 1:
        raise ValueError("Expected positive production limits")
    os.environ["STS2_DOTNET"] = str(Path("logs/m0-v5/dotnet9/dotnet.exe").resolve())
    os.environ["STS2_DOTNET_VERSION"] = "9.0.7"
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    config = json.loads(args.config.read_bytes())
    config["action_cap"] = args.cap
    if args.batch_delay < 0:
        raise ValueError("Negative batch delay")
    if (not 1 <= config["action_cap"] <= 512 or not 1 <= config["deck_length"][0]
            <= config["deck_length"][1] <= 40 or not 0 <= config["upgrade_rate"] <= 1
            or not config["hp"] or not all(1 <= hp <= 999 for hp in config["hp"])):
        raise ValueError("Invalid Ironclad distribution")
    if args.recycle < 1 or args.worker_mib < 1 or args.recycle > 1 and not args.host:
        raise ValueError("Resident mode requires the PRE0 host and positive budgets")
    versions = bind_host(args)
    if args.buffered_logs:
        client = BANK.f1.i2.engine_client
        client.EngineClient = buffered_client(client.EngineClient, client.EngineCancelled)
    with ExitStack() as stack:
        catalog = targets.open_worker(args.output, stack, versions).request("synthetic_catalog")
    ironclad, = [role for role in catalog["characters"] if role["name"] == "Ironclad"]
    allowed = ({c["id"] for c in ironclad["cards"]} | set(config["generated_allow"]) | {"FRANTIC_ESCAPE", "INFECTION", "TOXIC", "WITHER", "DISINTEGRATION", "MIND_ROT", "SLOTH", "WASTE_AWAY", "AMNESIA"}) - set(config["exclude"])
    torch.manual_seed(p0["config"]()["initialization_seed"])
    policy = v4.Policy().eval()
    if args.checkpoint:
        with closing(sqlite3.connect(args.checkpoint.resolve().as_uri()+"?mode=ro", uri=True)) as source:
            raw, expected = source.execute("SELECT payload, sha FROM snapshots WHERE step=?", (args.update,)).fetchone()
            if sha256(raw).hexdigest() != expected:
                raise ValueError("Checkpoint checksum mismatch")
            payload = p0["tensors"](raw)
            policy.load_state_dict(payload["model"])
        if digest(v4.checkpoint_policy(policy)) != payload["model_sha256"]:
            raise ValueError("Behavior model hash mismatch")
    model_hash = digest(v4.checkpoint_policy(policy))
    identity = dict(contract=CONTRACT, versions=versions, config=config, catalog=digest(catalog),
                    behavior=model_hash, torch=str(torch.__version__), inference_batch=args.batch, batch_delay=args.batch_delay,
                    allowed_cards=sorted(allowed),
                    source={name: sha256((HERE / name).read_bytes()).hexdigest()
                            for name in ("run.py", "batching.py", "transport.py")})
    stamp = digest(identity)
    statuses, phases, rooms = Counter(), Counter(), Counter()
    decisions = compressed = 0
    workers = []
    disk_before = disk_bytes(args.output)
    disk_limit = args.disk_mib * 2**20
    stop_reason = None
    with BANK.writer(args.output), closing(sqlite3.connect(args.output/"dataset.sqlite")) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS manifest (sha TEXT PRIMARY KEY, json BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS trajectories
            (ordinal INTEGER PRIMARY KEY, id TEXT UNIQUE, split TEXT, complete INTEGER, sha TEXT, payload BLOB);
            CREATE TABLE IF NOT EXISTS private_tasks
            (id TEXT PRIMARY KEY, recipe BLOB NOT NULL, cost BLOB NOT NULL);
        """)
        existing = db.execute("SELECT sha FROM manifest").fetchone()
        if existing and existing[0] != stamp:
            raise ValueError("Dataset identity changed")
        with db:
            db.execute("INSERT OR IGNORE INTO manifest VALUES (?,?)", (stamp, encode(identity)))
        db.execute(f"PRAGMA max_page_count={args.disk_mib * 2**20 // db.execute('PRAGMA page_size').fetchone()[0]}")
        def pending():
            for i in range(args.count):
                if db.execute("SELECT 1 FROM trajectories WHERE ordinal=?", (i,)).fetchone() is None:
                    yield (digest([stamp, i]), i, *root(catalog, config, i))

        pending_jobs = pending()
        active = {}
        inference = Inference(policy, args.batch, args.batch_delay) if args.batch > 1 else nullcontext(policy)
        with inference as infer, p0["Meter"]() as meter, ThreadPoolExecutor(max_workers=args.workers) as pool:
            warm = meter.start_phase()
            if disk_before >= disk_limit:
                stop_reason = "output_disk_limit"

            lanes = [Lane(args.output, versions, meter, args.recycle, args.worker_mib * 2**20)
                     for _ in range(args.workers)]

            def submit(lane):
                nonlocal stop_reason
                if stop_reason is not None:
                    return
                if perf_counter()-warm[0] >= args.seconds:
                    stop_reason = "duration"
                    return
                if (args.output/"STOP").exists():
                    stop_reason = "stop_file"
                    return
                job = next(pending_jobs, None)
                if job is not None:
                    future = pool.submit(collect, versions, policy, infer, model_hash, config, allowed,
                                         job, lane, args.fast)
                    active[future] = job, lane

            buffer = []
            last_commit = perf_counter()
            next_disk_check = 64

            def flush():
                nonlocal last_commit, stop_reason, compressed, decisions, next_disk_check
                if not buffer:
                    return
                started = perf_counter()
                try:
                    with db:
                        db.executemany("INSERT INTO trajectories VALUES (?,?,?,?,?,?)", [
                            (ordinal, task, split, record["complete"], sha, blob)
                            for ordinal, task, split, record, _, _, sha, blob in buffer])
                        db.executemany("INSERT INTO private_tasks VALUES (?,?,?)", [
                            (task, encode(spec), encode(cost))
                            for _, task, _, _, cost, spec, _, _ in buffer])
                except sqlite3.OperationalError as error:
                    if str(error) != "database or disk is full":
                        raise
                    stop_reason = "sqlite_disk_limit"
                    buffer.clear()
                    return
                phases["commit"] += perf_counter() - started
                last_commit = perf_counter()
                for _, _, _, record, cost, spec, _, blob in buffer:
                    phases.update(cost["phases"])
                    statuses[record["status"]] += 1
                    compressed += len(blob)
                    if record["complete"]:
                        rooms[f"{spec['act']}:{record['room']}"] += 1
                        decisions += record["length"]
                buffer.clear()
                if sum(statuses.values()) >= next_disk_check:
                    next_disk_check += 64
                    if disk_bytes(args.output) >= disk_limit:
                        stop_reason = "output_disk_limit"

            try:
                for lane in lanes:
                    submit(lane)
                while active:
                    done, _ = wait(active, return_when=FIRST_COMPLETED)
                    for future in done:
                        job, lane = active.pop(future)
                        task, ordinal, spec, split, _, _ = job
                        record, cost = future.result()
                        start = perf_counter()
                        data = encode(record)
                        blob = gzip.compress(data, compresslevel=3, mtime=0)
                        phases["encode_compress"] += perf_counter()-start
                        buffer.append((ordinal, task, split, record, cost, spec, sha256(data).hexdigest(), blob))
                        submit(lane)
                    if len(buffer) >= 12 or not active or perf_counter() - last_commit >= .2:
                        flush()
            finally:
                wait(active)
                for lane in lanes:
                    lane.close("production_stop")
                    workers.extend(lane.events)
            resources = meter.end_phase(warm)
    if args.batch > 1:
        phases.update(inference.timing)
    output_growth = disk_bytes(args.output) - disk_before
    elapsed = perf_counter()-START
    attempts = sum(statuses.values())
    complete = sum(rooms.values())
    summary = dict(manifest=stamp, model=model_hash, workers=args.workers, fast=args.fast,
                   attempts=attempts, complete=complete, decisions=decisions, statuses=statuses,
                   status_fractions={k: v/attempts for k, v in statuses.items()}, complete_by_room=rooms,
                   phases_s=phases, end_to_end_s=elapsed, resources=resources,
                   attempts_s=attempts/elapsed, complete_s=complete/elapsed, decisions_s=decisions/elapsed,
                   steady_complete_s=complete/resources["wall_s"],
                   steady_attempts_s=attempts/resources["wall_s"],
                   steady_decisions_s=decisions/resources["wall_s"],
                   compressed_bytes=compressed, compressed_bytes_s=compressed/elapsed,
                   process_count=len(workers), attempts_per_process=attempts/max(len(workers), 1),
                   worker_events=workers, stop_reason=stop_reason or "root_count",
                   disk_growth_bytes=output_growth, disk_growth_bytes_s=output_growth/elapsed,
                   inference_batch=args.batch, buffered_logs=args.buffered_logs,
                   recycle=args.recycle, batch_delay=args.batch_delay)
    output = args.output / f"run-{time_ns()}.json"
    output.write_bytes(encode(summary))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=HERE.parent/"m1-pre0/config.json")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--count", type=int, default=50000)
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--disk-mib", type=int, default=2048)
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--host", type=Path)
    parser.add_argument("--recycle", type=int, default=1)
    parser.add_argument("--worker-mib", type=int, default=512)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--update", type=int, default=0)
    parser.add_argument("--cap", type=int, default=256)
    parser.add_argument("--batch-delay", type=float, default=0.0001)
    parser.add_argument("--buffered-logs", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    produce(args)


