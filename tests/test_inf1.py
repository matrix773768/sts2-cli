"""Windows acceptance tests for INF1 without game or CUDA workloads."""

import os
import subprocess
import sys
from time import monotonic, sleep
import unittest
from unittest.mock import patch
import uuid

from tools.training_manager.common import HOME, ROOT, freeze, lease, read, write
from tools.training_manager.manager import Manager
from tools.training_manager.timing import duration
from tools.training_manager.windows import process_identity, resources


FIXTURE = "tests/inf1_task_fixture.py"
READY = dict(ram_mb=4096, disk_mb=4096, ac=True, idle_seconds=900, gpus=[{"free_mb": 3000}])


@unittest.skipUnless(os.name == "nt", "INF1 Windows Job Object integration")
class TrainingManagerTests(unittest.TestCase):
    def setUp(self):
        self.home = HOME / f"mock-{uuid.uuid4().hex[:8]}"
        self.manager = Manager(self.home)
        self.manager.control("mode", "Full")
        self.snapshot = dict(READY)
        self.process = None

    def tearDown(self):
        if self.process and self.process.poll() is None:
            self.manager.control("halt", True)
            self.process.wait(timeout=30)
        for row in self.manager.rows():
            if row["state"] in ("running", "pausing"):
                self.manager.request(row["id"], "force")
                self.wait(row["id"], "cancelled")
        for child in self.manager.children:
            child.wait(timeout=10)
        self.manager.db.close()

    def make(self, key, stages=None, **options):
        stages = stages or [self.stage("work", 3)]
        data = dict(id=key, name=key, type="simulation", cwd=".", mode="Any", max_retries=0,
                    output=(self.home / "jobs" / key).relative_to(ROOT).as_posix(),
                    python=sys.executable, inputs=[], stages=stages) | options
        return freeze(data, self.home)

    def stage(self, key, count, *extra, depends=(), **options):
        return dict(id=key, depends_on=list(depends), args=[FIXTURE, "{work}", str(count), *extra],
                    resume="checkpoint", boundary="committed unit", heavy=True, gpu=False, workers=1) | options

    def step(self):
        self.manager.step(lambda path, gpu: self.snapshot)

    def until(self, condition, *, tick=True, timeout=25):
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            if tick:
                self.step()
            result = condition()
            if result:
                return result
            sleep(.08)
        self.fail(f"Condition timed out: {[dict(row) for row in self.manager.rows()]}")

    def wait(self, key, state, **kwargs):
        return self.until(lambda: self.manager.job(key)["state"] == state, **kwargs)

    def stage_info(self, key):
        _, _, _, work = self.manager.inspect(self.manager.job(key))
        return read(work / "progress.json", {}) if work else {}

    def test_submission_sequence_dependencies_and_finite_retry(self):
        self.manager.submit(self.make("first", [
            self.stage("one", 3, "--failure", "once"),
            self.stage("two", 3, "--dependency", "{output}/one/units.json", depends=("one",))
        ], max_retries=1))
        self.manager.submit(self.make("second", [self.stage("work", 1)]))
        self.wait("second", "completed")
        first = self.manager.report(self.manager.job("first"))
        second = self.manager.report(self.manager.job("second"))
        self.assertEqual(first["state"], "completed")
        self.assertEqual(first["retries"], 1)
        self.assertEqual([run["stage"] for run in first["runs"]], ["one", "one", "two"])
        self.assertLessEqual(first["runs"][-1]["ended"], second["runs"][0]["launched"])
        self.manager.submit(self.make("fails", [
            self.stage("bad", 1, "--failure", "always"),
            self.stage("never", 1, depends=("bad",))
        ], max_retries=1))
        self.wait("fails", "failed")
        row = self.manager.report(self.manager.job("fails"))
        self.assertEqual(row["errors"], 2)
        self.assertIsNone(row["stages"]["never"])
        with self.assertRaisesRegex(ValueError, "No approved retry"):
            self.manager.request("fails", "retry")

    def test_pause_resume_without_replaying_units(self):
        self.manager.submit(self.make("pause", [self.stage("work", 24)]))
        self.until(lambda: self.stage_info("pause").get("done", 0) >= 3)
        self.manager.request("pause", "pause")
        self.wait("pause", "paused")
        count = self.stage_info("pause")["done"]
        self.assertGreaterEqual(count, 3)
        self.assertLess(count, 24)
        for child in self.manager.children:
            child.wait(timeout=10)
        self.manager.db.close()
        self.manager = Manager(self.home)
        self.manager.request("pause", "resume")
        self.wait("pause", "completed")
        checkpoint = self.home / "jobs/pause/work/units.json"
        self.assertEqual(read(checkpoint), list(range(24)))
        self.assertEqual(len(self.manager.report(self.manager.job("pause"))["runs"]), 2)

    def test_duplicate_id_configuration_and_output_collision(self):
        spec = self.make("identity")
        self.manager.submit(spec)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.manager.submit(spec)
        with self.assertRaisesRegex(ValueError, "configuration hash"):
            self.manager.submit(spec | {"budget_seconds": 3})
        wrong = self.make("wrong")
        (self.home / "jobs/wrong").mkdir()
        with self.assertRaises(FileExistsError):
            self.manager.submit(wrong)
        with self.assertRaisesRegex(ValueError, "Task output must be"):
            self.manager.submit(spec | {"output": "logs/m1-dc1-formal"})
        output = self.home / "jobs/identity/task.json"
        write(output, spec | {"name": "changed"})
        self.wait("identity", "failed")
        self.assertEqual(self.manager.job("identity")["reason"], "Output identity has changed")

    def test_resource_modes_and_protection(self):
        stage = self.stage("work", 18, workers=4, light_workers=1,
                           light_args=[FIXTURE, "{work}", "18", "--delay", ".12"])
        self.manager.submit(self.make("modes", [stage]))
        for mode, override, message in (
                ("Full", {"ram_mb": 1}, "ram_mb below"),
                ("Full", {"disk_mb": 1}, "disk_mb below"),
                ("Idle", {"idle_seconds": 0}, "waiting for input idle"),
                ("Idle", {"ac": False}, "AC unavailable")):
            self.manager.control("mode", mode)
            self.snapshot = READY | override
            self.step()
            row = self.manager.job("modes")
            self.assertEqual(row["state"], "queued")
            self.assertIn(message, row["reason"])
        self.snapshot = READY
        self.manager.control("mode", "Light")
        self.until(lambda: self.stage_info("modes").get("done", 0) >= 2)
        self.manager.control("mode", "Full")
        self.wait("modes", "completed")
        runs = self.manager.report(self.manager.job("modes"))["runs"]
        self.assertEqual([run["profile"] for run in runs], ["Light", "Full"])
        self.assertEqual(runs[0]["outcome"]["state"], "paused")
        self.assertEqual(runs[0]["command"][-2:], ["--delay", ".12"])
        self.manager.submit(self.make("gpu", [self.stage("work", 1, gpu=True)]))
        self.snapshot = READY | {"gpus": None}
        self.step()
        self.assertIn("GPU 0", self.manager.job("gpu")["reason"])
        real = resources(self.home, gpu=True)
        self.assertGreater(real["disk_mb"], 0)
        self.assertGreater(real["ram_mb"], 0)
        self.assertIsInstance(real["idle_seconds"], (int, float))

    def test_idle_input_and_sustained_resource_loss_pause(self):
        self.manager.submit(self.make("idle", [self.stage("work", 22, "--delay", ".2")]))
        self.manager.control("mode", "Idle")
        self.until(lambda: self.stage_info("idle").get("done", 0) >= 2)
        self.snapshot = READY | {"idle_seconds": 0}
        self.wait("idle", "paused")
        self.assertIn("input idle", self.manager.job("idle")["reason"])
        self.snapshot = READY
        self.wait("idle", "running")
        for change in ({"ram_mb": 1}, {}):
            self.snapshot = READY | change
            self.step()
            self.assertEqual(self.manager.job("idle")["state"], "running")
        self.snapshot = READY | {"ram_mb": 1}
        self.wait("idle", "paused")
        self.assertIn("ram_mb", self.manager.job("idle")["reason"])
        self.snapshot = READY
        self.wait("idle", "completed")
        self.assertEqual(read(self.home / "jobs/idle/work/units.json"), list(range(22)))

    def test_budget_and_force_stop(self):
        self.manager.submit(self.make("budget", [self.stage("work", 30)], budget_seconds=1))
        self.wait("budget", "cancelled")
        self.assertEqual(self.manager.job("budget")["reason"], "budget")
        self.manager.submit(self.make("force", [self.stage("work", 100)]))
        self.until(lambda: self.stage_info("force").get("done", 0) >= 1)
        self.manager.request("force", "force")
        self.wait("force", "cancelled")
        run = self.manager.report(self.manager.job("force"))["runs"][-1]
        self.assertIsNone(process_identity(run["owner"]["gate"]["pid"]))

    def test_duplicate_manager_and_adoption_after_manager_crash(self):
        self.manager.submit(self.make("adoption", [self.stage("work", 100)]))
        command = [sys.executable, "-m", "tools.training_manager", "--home", self.home.name, "start", "--foreground"]
        with lease(self.home / "manager.lock") as acquired:
            self.assertTrue(acquired)
            repeat = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(repeat.returncode, 2)
            self.assertIn("already owns", repeat.stderr)
        self.process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL)
        self.until(lambda: self.stage_info("adoption").get("done", 0) >= 2, tick=False)
        row = self.manager.job("adoption")
        owner = self.manager.report(row)["runs"][0]["owner"]
        self.process.kill()
        self.process.wait(timeout=10)
        self.assertEqual(process_identity(owner["process"]["pid"]), owner["process"])
        self.process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL)
        self.until(lambda: self.stage_info("adoption").get("done", 0) >= 5, tick=False)
        self.assertEqual(self.manager.job("adoption")["token"], row["token"])
        self.manager.request("adoption", "pause")
        self.wait("adoption", "paused", tick=False)
        self.assertEqual(len(self.manager.report(self.manager.job("adoption"))["runs"]), 1)

    def test_worker_crash_releases_tree_and_marks_interrupted(self):
        self.manager.submit(self.make("crash", [self.stage("work", 90)], max_retries=1, budget_seconds=120))
        def recent():
            run = self.manager.report(self.manager.job("crash"))["runs"][0]
            pulse = run.get("heartbeat")
            return run if pulse and pulse["elapsed"] >= 1 else None
        run = self.until(recent)
        owner = run["owner"]
        # Only terminate the identified test supervisor, not its gate or any game process.
        self.assertEqual(process_identity(owner["process"]["pid"]), owner["process"])
        os.kill(owner["process"]["pid"], 15)
        with patch("tools.training_manager.timing.time", return_value=run["heartbeat"]["observed"] + 9 * 3600):
            self.wait("crash", "interrupted")
        self.assertIsNone(process_identity(owner["gate"]["pid"]))
        row = self.manager.job("crash")
        self.assertEqual(row["errors"], 1)
        self.assertEqual(row["retries"], 0)
        report = self.manager.report(row)
        outcome = report["runs"][0]["outcome"]
        self.assertGreater(outcome["detected"] - outcome["ended"], 8 * 3600)
        self.assertFalse(outcome["exit_confirmed"])
        self.assertTrue(report["timing"]["unknown_tail"])
        self.assertLessEqual(run["heartbeat"]["elapsed"], report["seconds"])
        self.assertLess(report["seconds"], 20)
        with self.assertRaisesRegex(ValueError, "另行批准"):
            self.manager.request("crash", "retry")

    def test_elapsed_is_independent_of_wall_clock_jumps(self):
        self.assertEqual(duration(dict(state="completed", started=5000,ended=1200,elapsed=7)), 7)
        self.assertEqual(duration(dict(state="interrupted", started=5000,ended=82000)), 0)


if __name__ == "__main__":
    unittest.main()
