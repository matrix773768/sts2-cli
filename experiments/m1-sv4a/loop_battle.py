"""Resident prediction episodes and compact paired battle/experience ledgers."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
import gzip
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import random
import sqlite3
from threading import local
from time import perf_counter

import numpy as np
import torch

from loop_common import ROOT, checksum, digest, sources, write_json
from sv_data import decoded, encode
from sv_eval import metrics
from evaluate import bind, teacher
from inference import InferenceGroup
from loop_policy import BattlePolicy, NetworkPolicy

SCHEMA = "sts2.sv4a.prediction_only.v1"


class Host:
    def __init__(self, output, build, cfg):
        self.output = output
        config = json.loads((ROOT / "experiments/m1-sv3a/config.json").read_bytes())
        self.runtime, prior = bind(output, ROOT / config["host"])
        self.identity = json.loads((build / "build.json").read_bytes())
        for name, value in self.identity["artifacts"].items():
            if checksum(build / name) != value:
                raise ValueError(f"Changed overlay artifact {name}")
        self.engine = self.runtime["BANK"].f1.i2.engine_client
        self.client = self._client()
        self.project = self.runtime["targets"].project
        command = self.engine.headless_command()
        self.engine.headless_command = lambda: [*command[:-1],
            str(build / "host/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll")]
        os.environ.update(I1_SOLVER=str(build / "solver-bin/CombatSolver.dll"),
                          I1_RITSU=self.identity["ritsu"], I1_LOG=".")
        self.version = dict(game=prior["game"], base_solver=self.identity["base_solver"], coreclr=prior["coreclr"],
                            overlay=self.identity["artifacts"], probe=self.identity["sources"])
        self.lanes = []
        self.thread = local()
        self.workers = cfg["workers"]
        self.lane_recycles = cfg.get("lane_recycles", 80)

    def _client(self):
        from transport import buffered_client
        parent = buffered_client(self.engine.EngineClient, self.engine.EngineCancelled)

        class CompactClient(parent):
            def _drain(self, stream, filename):
                if stream is not self.proc.stdout:
                    return super()._drain(stream, filename)
                try:
                    with (self.log_dir / filename).open("wb", buffering=65536) as log:
                        for line in iter(stream.readline, b""):
                            if not line.lstrip().startswith(b"{"):
                                log.write(line)
                                continue
                            if b'"type":"error"' in line[:160] or b'"status":"error"' in line[:300]:
                                log.write(line)
                            self._responses.put(line)
                except OSError as error:
                    self._responses.put(error)
                finally:
                    self._responses.put(None)
        return CompactClient

    def lane(self):
        if not hasattr(self.thread, "lane"):
            self.thread.lane = Lane(self, len(self.lanes))
            self.lanes.append(self.thread.lane)
        return self.thread.lane

    def close(self):
        for lane in self.lanes:
            lane.close()
        self.lanes = []
        self.thread = local()


class Lane:
    def __init__(self, host, number):
        self.host, self.number = host, number
        self.client, self.roots = None, 0

    def open(self):
        if self.client is None:
            self.client = self.host.client(log_root=self.host.output / "engine", command_timeout=45)
            actual = self.request("i1_s3a_identity")
            expected = self.host.identity["artifacts"]["solver-bin/CombatSolver.dll"]
            if actual["sha256"] != expected:
                raise ValueError("Loaded Solver does not match the overlay")
            self.roots = 0
        self.roots += 1

    def request(self, command, **args):
        response = self.client.send(dict(cmd=command, **args))
        if response.get("type") == "error":
            raise RuntimeError(response.get("message") or response.get("error") or command)
        return response

    def close(self):
        if self.client is not None:
            try:
                self.client.close()
            finally:
                self.client = None

    def reset(self):
        if self.roots >= self.host.lane_recycles:
            self.close()
            return
        for cmd in ("i1_n2_close", "i1_release", "f1_3c_release", "pre0_abandon"):
            self.request(cmd)


class TeacherBattle:
    def __init__(self, actor, runtime, rng, forced=None):
        self.actor, self.target, self.rng = actor, runtime["targets"], rng
        self.history = torch.zeros(self.target.base.WIDTH)
        self.timing, self.counts, self.trace = Counter(), Counter(), []
        self.forced = forced

    @torch.inference_mode()
    def act(self, observation, lane, position):
        tick = perf_counter()
        decision = self.target.Decision(observation)
        logits, _, state, actions = self.actor(decision, self.history)
        probabilities = logits.softmax(0).tolist()
        if self.forced and position == 0:
            index = next(a["index"] for a in observation["actions"] if a["kind"] == "play_card"
                         and observation["hand"][a["card"]]["id"] == self.forced.upper())
            probability, mode = 1., "diagnostic"
        else:
            index = self.rng.choices(range(len(actions)), weights=probabilities, k=1)[0]
            probability, mode = probabilities[index], "actor"
        self.history = self.actor.remember(self.history, state, actions[index])
        self.timing["inference"] += perf_counter() - tick
        return index, probability, mode

    def after(self, state):
        pass


@torch.inference_mode()
def collect(lane, policy, definition, manifest, job, task, fixture=None):
    begin = perf_counter()
    ordinal, private, split, family, room = job
    cap = manifest["config"]["action_cap"]
    state, steps, reason, reset_issue = {}, [], None, None
    timing = Counter()
    status = "error"
    try:
        tick = perf_counter()
        lane.open()
        kwargs = {} if fixture is None else {"sv1_fixture": fixture}
        response = lane.request("pre0_start", spec=private, cap=cap, **kwargs)
        if "episode" not in response:
            raise RuntimeError(f"Unexpected initial decision {response.get('decision')}")
        state = response["episode"]
        timing["root"] = perf_counter() - tick
        while state["status"] == "active" and len(steps) < cap:
            observation = lane.host.project(state["observation"])
            position = len(steps)
            if state["actions"] != position:
                raise RuntimeError("Unexpected executing episode cursor")
            index, probability, mode = policy.act(observation, lane, position)
            action = observation["actions"][index]
            if not 0 < probability <= 1 or action["index"] != index:
                raise ValueError("Invalid action index or conditional sampling probability")
            tick = perf_counter()
            state = lane.request("i1_n2_step", position=position, index=index)["episode"]
            timing["rpc"] += perf_counter() - tick
            policy.after(state)
            advanced = state["actions"] == position + 1
            steps.append(dict(position=position, observation=observation, action=action, advanced=advanced,
                              mode=mode, behavior_logp=math.log(probability)))
            if not advanced or state["status"] == "invalid_action":
                raise RuntimeError("Executing Solver rejected the verified public move")
        status = state["status"]
        if status == "active":
            status, reason = "truncated", "action_cap"
        else:
            reason = state.get("detail") or state.get("public_reason")
        try:
            lane.reset()
        except (RuntimeError, ValueError, OSError, TimeoutError) as error:
            reset_issue = str(error)
            lane.close()
    except (RuntimeError, ValueError, KeyError, OSError, TimeoutError) as error:
        status, reason = "error", str(error)
        lane.close()
    view, result = state.get("terminal_observation"), state.get("result") or {}
    terminal = view | {"gold": result.get("gold")} if view is not None else None
    complete = status in ("predicted_win", "death") and bool(steps) and all(s["advanced"] for s in steps) and terminal is not None
    if status in ("predicted_win", "death") and not complete:
        status, reason = "error", "incomplete_terminal_record"
    row = dict(contract=SCHEMA, evidence="prediction_only", purpose=manifest["purpose"],
        id=task, root={k: v for k,v in private.items() if k != "seed"}, split=split, family=family,
        source=manifest["config"]["version"], room=room, steps=steps, status=status, reason=reason,
        complete=complete, terminal=terminal, cumulative_loss=result.get("cumulative_loss"), length=len(steps),
        behavior=dict(model=SCHEMA, model_sha256=digest(definition), mode="conditional"), reset_issue=reset_issue)
    return dict(row=row, ordinal=ordinal, counts=dict(policy.counts), search=policy.trace,
                timing=dict(timing + policy.timing), wall_s=perf_counter() - begin)


def read_ledger(path, full=True):
    uri = (path / "results.sqlite").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        for expected, blob in db.execute("SELECT sha,payload FROM results ORDER BY ordinal"):
            row = decoded(expected, blob)
            if not full:
                row["row"].pop("steps")
                row.pop("search")
            yield row


def summary(output, wall):
    records = list(read_ledger(output, full=False))
    rows = [item["row"] for item in records]
    report = metrics(rows)
    counts, timing = Counter(), Counter()
    for record in records:
        counts.update(record["counts"])
        timing.update(record["timing"])
    report.update(wall_s=wall, complete_per_s=report["complete"]/wall,
        counts=dict(counts), timing=dict(timing),
        root_ms=np.quantile([r["wall_s"] * 1000 for r in records], [.5,.9,.95,.99]).tolist(),
        failures=[dict(ordinal=r["ordinal"], status=r["row"]["status"], reason=r["row"]["reason"],
                       encounter=r["row"]["root"]["encounter"]) for r in records if not r["row"]["complete"]],
        reset_errors=sum(bool(r["reset_issue"]) for r in rows),
        by_hp={str(hp):metrics([r for r in rows if r["root"]["hp"] == hp])
               for hp in sorted({r["root"]["hp"] for r in rows})})
    write_json(output / "summary.json", report)
    return report


def run(host, manifest_path, output, cfg, weights=None, condition=None, budget=0, epsilon=0.,
        attempts=None, max_new=None, forced=None):
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_bytes())
    if weights is None:
        prior, actor_sha = teacher(host.runtime, ROOT / "logs/nosl3c-iii-a2-01/training/training.sqlite", 84)
        definition = dict(version=SCHEMA, teacher=actor_sha, host=host.version, sampling="frozen-v4-categorical")
        value = None
    else:
        value = NetworkPolicy(weights, condition, budget, epsilon, host.version, cfg)
        definition = value.definition
    definition = definition | {"forced_first_diagnostic": forced} if forced else definition
    contract = dict(manifest=checksum(manifest_path), definition=definition, purpose=manifest["purpose"],
        attempts=attempts, workers=cfg["workers"], groups=cfg["inference_groups"],
        batch=cfg["inference_batch"], sources=sources("loop_policy.py", "loop_battle.py"))
    identity = digest(contract)
    jobs = manifest["jobs"][:attempts]
    with closing(sqlite3.connect(output / "writer.sqlite", timeout=0)) as lock, ExitStack() as resources:
        lock.execute("BEGIN EXCLUSIVE")
        db = resources.enter_context(closing(sqlite3.connect(output / "results.sqlite", timeout=30)))
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS contract(sha TEXT PRIMARY KEY,json BLOB);
            CREATE TABLE IF NOT EXISTS results(ordinal INTEGER PRIMARY KEY,sha TEXT,payload BLOB);
            CREATE TABLE IF NOT EXISTS sessions(seconds REAL);
        """)
        old = db.execute("SELECT sha FROM contract").fetchone()
        if old is not None and old[0] != identity:
            raise ValueError("Run identity changed")
        with db:
            db.execute("INSERT OR IGNORE INTO contract VALUES (?,?)", (identity, encode(contract)))
        seen = {row[0] for row in db.execute("SELECT ordinal FROM results")}
        todo = [job for job in jobs if job[0] not in seen][:max_new]
        if todo:
            groups = [resources.enter_context(InferenceGroup(value.forward, cfg["inference_batch"], .00015))
                      for _ in range(cfg["inference_groups"])] if value else []
            tick = perf_counter()

            def one(job):
                lane = host.lane()
                rng = random.Random(int(digest([manifest["config"]["policy_seed"], job[0]]), 16))
                if value is None:
                    controller = TeacherBattle(prior, host.runtime, rng, forced)
                else:
                    forward = groups[lane.number % len(groups)] if groups else lambda rows: next(value.forward([(rows,)]))
                    controller = BattlePolicy(value, host.project, forward, rng, forced)
                return collect(lane, controller, definition, manifest, job, digest([identity, job[0]]))

            try:
                with ThreadPoolExecutor(max_workers=cfg["workers"]) as pool:
                    for offset in range(0, len(todo), cfg["workers"] * 4):
                        group = todo[offset:offset + cfg["workers"] * 4]
                        for item in pool.map(one, group):
                            raw = encode(item)
                            with db:
                                db.execute("INSERT INTO results VALUES (?,?,?)",
                                    (item["ordinal"], sha256(raw).hexdigest(), gzip.compress(raw, compresslevel=3, mtime=0)))
                        if offset % (cfg["workers"] * 16) == 0:
                            print(output.name, len(seen) + offset + len(group), "/", len(jobs), flush=True)
            finally:
                host.close()
                with db:
                    db.execute("INSERT INTO sessions VALUES (?)", (perf_counter() - tick,))
        wall = db.execute("SELECT sum(seconds) FROM sessions").fetchone()[0]
    if wall:
        return summary(output, wall)
