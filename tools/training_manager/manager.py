"""SQLite scheduling and reconciliation for explicitly submitted plans."""

from contextlib import contextmanager
import json
import os
import sqlite3
import subprocess
import sys
from time import sleep, time
import uuid

from .common import ROOT, command, lease, output_for, read, settings, validate, verify_assets, write
from .windows import process_identity, resources


ACTIVE = ("running", "pausing")
TERMINAL = ("completed", "failed", "cancelled", "interrupted")


class Manager:
    def __init__(self, home):
        self.home = home
        home.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(home / "queue.sqlite", timeout=15, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS control (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, spec TEXT NOT NULL, state TEXT NOT NULL, stage INTEGER DEFAULT 0,
                submitted REAL NOT NULL, started REAL, paused_at REAL, paused_seconds REAL DEFAULT 0,
                seconds REAL DEFAULT 0, retries INTEGER DEFAULT 0, errors INTEGER DEFAULT 0,
                intent TEXT, reason TEXT, token TEXT, exit_code INTEGER
            );
            CREATE TABLE IF NOT EXISTS runs (
                token TEXT PRIMARY KEY, job TEXT REFERENCES jobs(id), stage INTEGER NOT NULL,
                profile TEXT NOT NULL, launched REAL NOT NULL, ended REAL, result TEXT, command TEXT NOT NULL
            );
        """)
        self.samples = {}
        self.children = []

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def get_control(self, key, default=None):
        row = self.db.execute("SELECT value FROM control WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def control(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO control VALUES (?,?)", (key, json.dumps(value)))

    def job(self, key):
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        if not row:
            raise ValueError(f"Unknown task: {key}")
        return row

    def rows(self):
        return self.db.execute("SELECT * FROM jobs ORDER BY submitted,rowid").fetchall()

    def update(self, row, **changes):
        clause = ", ".join(f"{key}=?" for key in changes)
        self.db.execute(f"UPDATE jobs SET {clause} WHERE id=?", (*changes.values(), row["id"]))

    def submit(self, spec):
        validate(spec, self.home)
        verify_assets(spec)
        output = output_for(self.home, spec)
        with self.transaction():
            if self.db.execute("SELECT 1 FROM jobs WHERE id=?", (spec["id"],)).fetchone():
                raise ValueError(f"Duplicate task ID: {spec['id']}")
            output.parent.mkdir(parents=True, exist_ok=True)
            # mkdir reserves the directory even across separate queue database copies.
            output.mkdir()
            write(output / "task.json", spec)
            self.db.execute("INSERT INTO jobs(id,spec,state,submitted) VALUES (?,?,?,?)",
                            (spec["id"], json.dumps(spec), "queued", time()))

    def inspect(self, row):
        spec = json.loads(row["spec"])
        output = output_for(self.home, spec)
        stage = spec["stages"][row["stage"]] if row["stage"] < len(spec["stages"]) else None
        work = output / stage["id"] if stage else None
        if work and work.resolve() != work:
            raise ValueError(f"Stage directory must not redirect: {work}")
        return spec, output, stage, work

    def request(self, key, operation):
        with self.transaction():
            row = self.job(key)
            spec, _, stage, _ = self.inspect(row)
            state = row["state"]
            if operation in ("cancel", "force") and state not in ("completed", "cancelled"):
                if state in ACTIVE:
                    self.update(row, state="pausing", intent=operation, reason=operation)
                else:
                    paused = max(0, time() - row["paused_at"]) if row["paused_at"] else 0
                    self.update(row, state="cancelled", intent=None, reason=operation,
                                paused_at=None, paused_seconds=row["paused_seconds"] + paused)
            elif operation == "pause" and state in (*ACTIVE, "queued", "paused"):
                if row["intent"] in ("cancel", "force"):
                    raise ValueError(f"Cancellation already requested: {key}")
                if state in ACTIVE:
                    self.update(row, state="pausing", intent="pause", reason="pause")
                else:
                    self.update(row, state="paused", intent="pause", reason="pause", paused_at=row["paused_at"] or time())
            elif operation == "resume" and state == "paused":
                self.update(row, state="queued", intent=None, reason=None)
            elif operation == "retry" and state in ("failed", "interrupted"):
                if row["retries"] >= spec["max_retries"] or (row["token"] and stage["resume"] == "none"):
                    raise ValueError(f"No approved retry available: {key}")
                self.update(row, state="queued", intent=None, reason=None, retries=row["retries"] + 1)
            else:
                raise ValueError(f"Cannot {operation} a {state} task")
            if state in ACTIVE:
                self.signal(self.job(key))
        if self.job(key)["state"] == "cancelled":
            self.report(self.job(key))

    def reason(self, spec, stage, cfg, snapshot, starting):
        mode = cfg["mode"]
        if not cfg["enabled"] or self.get_control("halt"):
            return "manager stopped"
        if spec["mode"] not in ("Any", mode):
            return f"requires {spec['mode']} mode"
        if mode == "Light" and (stage["gpu"] or (stage["heavy"] and "light_args" not in stage)):
            return "Light mode excludes this stage"
        if (cfg["require_ac"] or mode == "Idle") and snapshot["ac"] is not True:
            return "AC unavailable"
        if mode == "Idle" and (starting or stage["heavy"] or stage["gpu"]):
            idle = snapshot["idle_seconds"]
            if idle is None or idle < cfg["idle_seconds"] - (0 if starting else min(5, cfg["idle_seconds"] / 2)):
                return "waiting for input idle"
        for key in ("ram_mb", "disk_mb"):
            limit = max(cfg[f"min_{key}"], stage.get(f"min_{key}", 0))
            if snapshot[key] is None or snapshot[key] < limit:
                return f"{key} below {limit} or unavailable"
        if stage["gpu"]:
            limit = max(cfg["min_vram_mb"], stage.get("min_vram_mb", 0))
            device = (snapshot["gpus"] or [None])[0]
            if not device or device["free_mb"] is None or device["free_mb"] < limit:
                return f"GPU 0 free memory below {limit} MiB or unavailable"
        return None

    def signal(self, row):
        spec, _, _, work = self.inspect(row)
        request = read(work / "request.json", {})
        if request.get("token") == row["token"] and request["sha256"] == spec["sha256"]:
            marker = work / "attempts" / row["token"] / "stop.json"
            if read(marker, {}).get("reason") != row["intent"]:
                write(marker, {"reason": row["intent"]})

    def stop(self, shutdown):
        with self.transaction():
            self.control("enabled", False)
            if shutdown:
                self.control("halt", True)
            for row in self.rows():
                if row["state"] in ACTIVE and not row["intent"]:
                    self.update(row, state="pausing", intent="automatic", reason="manager stopped")
                    self.signal(self.job(row["id"]))

    def report(self, row, *, persist=True):
        spec, output, stage, work = self.inspect(row)
        result = dict(row) | {"spec": spec, "current_stage": stage["id"] if stage else None,
                             "progress": read(work / "progress.json") if work else None}
        result["runs"] = []
        result["resource_snapshot"] = self.get_control("resources")
        if row["paused_at"]:
            result["paused_seconds"] += max(0, time() - row["paused_at"])
        for run in self.db.execute("SELECT * FROM runs WHERE job=? ORDER BY launched", (row["id"],)):
            name = spec["stages"][run["stage"]]["id"]
            attempt = output / name / "attempts" / run["token"]
            record = dict(run) | dict(command=json.loads(run["command"]), stage=name,
                cwd=spec["cwd"], owner=read(attempt / "owner.json"), child=read(attempt / "child.json"),
                stdout=str(attempt / "stdout.log"), stderr=str(attempt / "stderr.log"),
                outcome=json.loads(run["result"]) if run["result"] else None)
            record.pop("result")
            if run["ended"] is None:
                result["seconds"] += max(0, time() - (record["owner"] or {}).get("started", run["launched"]))
            result["runs"].append(record)
        result["stages"] = {
            item["id"]: read(output / item["id"] / "progress.json") for item in spec["stages"]
        }
        if persist and row["state"] in TERMINAL:
            write(output / "report.json", result)
        return result

    def begin(self, row, spec, output, stage, work, cfg):
        validate(spec, self.home)
        if read(output / "task.json") != spec:
            raise ValueError("Output identity has changed")
        verify_assets(spec)
        remaining = spec["budget_seconds"] - row["seconds"] if "budget_seconds" in spec else None
        if remaining is not None and remaining <= 0:
            self.update(row, state="cancelled", reason="budget", intent=None)
            return
        work.mkdir(exist_ok=True)
        profile = cfg["mode"]
        args = command(spec, stage, work, output, profile)
        with lease(work / "attempt.lock") as acquired:
            if not acquired:
                return
            token = uuid.uuid4().hex
            path = work / "attempts" / token
            path.mkdir(parents=True)
            request = dict(token=token, sha256=spec["sha256"], command=args, cwd=str((ROOT / spec["cwd"]).resolve()),
                           remaining=remaining, grace=stage.get("stop_grace_seconds", spec.get("stop_grace_seconds", 60)),
                           resume=stage["resume"])
            write(path / "launch.json", request)
            write(work / "request.json", request)
            now = time()
            self.db.execute("INSERT INTO runs(token,job,stage,profile,launched,command) VALUES (?,?,?,?,?,?)",
                            (token, row["id"], row["stage"], profile, now, json.dumps(args)))
            paused = max(0, now - row["paused_at"]) if row["paused_at"] else 0
            self.update(row, state="running", started=row["started"] or now, token=token, reason=None,
                        paused_at=None, paused_seconds=row["paused_seconds"] + paused, exit_code=None)
        # Called after committing the launch ticket. Recovery can fence a launch that never arrived.
        return [sys.executable, "-m", "tools.training_manager.worker", str(work), token]

    def finish(self, row, spec, stage, run, outcome):
        code, end, state = outcome["exit_code"], outcome["ended"], outcome["state"]
        self.db.execute("UPDATE runs SET ended=?,result=? WHERE token=?", (end, json.dumps(outcome), run["token"]))
        elapsed = row["seconds"] + max(0, end - outcome["started"])
        intent = row["intent"]
        changes = dict(seconds=elapsed, exit_code=code, reason=outcome.get("reason") or row["reason"], intent=None)
        if state == "completed":
            changes.update(stage=row["stage"] + 1, token=None)
        if intent in ("cancel", "force") or state == "cancelled":
            state = "cancelled"
        elif state == "completed":
            if changes["stage"] == len(spec["stages"]):
                changes["reason"] = None
            elif intent:
                state = "paused"
            else:
                state = "queued"
                changes["reason"] = None
        elif state in ("failed", "interrupted"):
            changes["errors"] = row["errors"] + 1
            if intent is None and stage["resume"] != "none" and row["retries"] < spec["max_retries"]:
                changes["retries"] = row["retries"] + 1
                state = "queued"
        if state == "paused":
            changes.update(paused_at=end, intent="pause" if intent == "pause" else None)
        self.update(row, state=state, **changes)

    def reconcile(self, row, spec, stage, work, cfg, snapshot):
        run = self.db.execute("SELECT * FROM runs WHERE token=?", (row["token"],)).fetchone()
        attempt = work / "attempts" / run["token"]
        owner = read(attempt / "owner.json")
        if owner and (owner["token"] != run["token"] or owner["sha256"] != spec["sha256"]):
            raise ValueError(f"Attempt owner does not match the recorded task: {row['id']}")
        with lease(work / "attempt.lock") as acquired:
            if acquired:
                result = read(attempt / "result.json")
                if result:
                    if result["token"] != run["token"]:
                        raise ValueError("Attempt result identity changed")
                    self.finish(row, spec, stage, run, result)
                elif (owner and owner.get("gate") and
                      process_identity(owner["gate"]["pid"]) == owner["gate"]):
                    return
                elif time() - run["launched"] > 5:
                    write(work / "request.json", {})
                    self.finish(row, spec, stage, run,
                                dict(state="interrupted", started=(owner or {}).get("started", run["launched"]),
                                     ended=time(), exit_code=None, reason="attempt exited without a result"))
                return
        if not owner or not owner["process"] or process_identity(owner["process"]["pid"]) != owner["process"]:
            return
        reason = self.reason(spec, stage, cfg, snapshot, starting=False)
        if not reason and stage.get("light_args") and ((cfg["mode"] == "Light") != (run["profile"] == "Light")):
            reason = "resource profile changed"
        if reason in ("manager stopped", "AC unavailable", "waiting for input idle", "resource profile changed"):
            interrupt = True
        else:
            old, count = self.samples.get(run["token"], (None, 0))
            count = count + 1 if old == reason and reason else int(bool(reason))
            self.samples = {run["token"]: (reason, count)}
            interrupt = count >= cfg["resource_samples"]
        intent = row["intent"] or ("automatic" if interrupt else None)
        if intent:
            self.update(row, state="pausing", intent=intent, reason=reason or row["reason"] or intent)
            self.signal(self.job(row["id"]))

    def step(self, probe=resources):
        self.children = [child for child in self.children if child.poll() is None]
        with self.transaction():
            cfg = settings(self.home)
            cfg["mode"] = self.get_control("mode", cfg["mode"])
            cfg["enabled"] = self.get_control("enabled", cfg["enabled"])
            rows = self.rows()
        tasks = [(row, *self.inspect(row)) for row in rows if row["state"] in (*ACTIVE, "queued", "paused")]
        gpu = any(stage["gpu"] for row, spec, output, stage, work in tasks if row["intent"] != "pause")
        snapshot = probe(self.home, gpu)
        with self.transaction():
            self.control("resources", snapshot | {"timestamp": time()})
            active = self.db.execute("SELECT * FROM jobs WHERE state IN ('running','pausing')").fetchone()
            if active:
                spec, _, stage, work = self.inspect(active)
                self.reconcile(active, spec, stage, work, cfg, snapshot)
                row = self.job(active["id"])
                if row["state"] in TERMINAL:
                    self.report(row)
                return
            for row in self.rows():
                if row["state"] not in ("queued", "paused") or row["intent"] == "pause":
                    continue
                spec, output, stage, work = self.inspect(row)
                reason = self.reason(spec, stage, cfg, snapshot, starting=True)
                if reason:
                    if row["reason"] != reason:
                        self.update(row, reason=reason)
                    continue
                try:
                    launch = self.begin(row, spec, output, stage, work, cfg)
                except (OSError, ValueError) as error:
                    self.update(row, state="failed", reason=str(error), errors=row["errors"] + 1, exit_code=None)
                    launch = None
                updated = self.job(row["id"])
                if updated["state"] in TERMINAL:
                    self.report(updated)
                break
            else:
                launch = None
        if launch:
            try:
                child = subprocess.Popen(launch, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                self.children.append(child)
            except OSError as error:
                print(f"Worker launch failed: {error}", flush=True)

    def run(self, once=False):
        with lease(self.home / "manager.lock") as acquired:
            if not acquired:
                raise ValueError("An INF1 manager already owns this queue")
            owner = process_identity(os.getpid())
            write(self.home / "manager.json", owner)
            if not once:
                with self.transaction():
                    self.control("halt", False)
                print(f"INF1 manager running (PID {os.getpid()})", flush=True)
            while True:
                self.step()
                if once or (self.get_control("halt") and not any(r["state"] in ACTIVE for r in self.rows())):
                    break
                sleep(settings(self.home)["poll_seconds"])
