"""Regression tests for the loaded dashboard revision and incident admission."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.training_manager.common import HOME, checksum, identity, write
from tools.training_manager.dashboard import __main__ as web
from tools.training_manager.dashboard import backend
from tools.training_manager import timing


class DashboardRevisionTests(unittest.TestCase):
    def setUp(self):
        HOME.mkdir(parents=True, exist_ok=True)
        temp = TemporaryDirectory(dir=HOME)
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)

    def test_running_revision_is_reused(self):
        record = {"revision":"current"}
        with (patch.object(web, "service_revision", return_value="current"),
              patch.object(web, "existing", return_value=record),
              patch.object(web, "close_old_service") as close,
              patch.object(web, "detach") as detach):
            self.assertEqual(web.ensure_service(self.home, 8765), record)
        close.assert_not_called()
        detach.assert_not_called()

    def test_old_process_is_closed_before_launch(self):
        legacy = {"revision":None}
        current = {"revision":"new"}
        with (patch.object(web, "service_revision", return_value="new"),
              patch.object(web, "existing", side_effect=[legacy,current]),
              patch.object(web, "close_old_service") as close,
              patch.object(web, "detach") as detach,
              patch.object(web, "sleep")):
            self.assertEqual(web.ensure_service(self.home, 8765), current)
        close.assert_called_once_with(self.home,8765,legacy)
        detach.assert_called_once()

    def test_live_static_files_and_health_revision_remain_together(self):
        static = self.home/"dashboard/static"
        static.mkdir(parents=True)
        for file, _ in web.STATIC.values():
            (static/file).write_bytes(b"original")
        with patch.object(web, "DASHBOARD_ROOT", self.home), web.Dashboard(self.home,0) as server:
            self.assertEqual(server.revision, web.service_revision())
            (static/"app.js").write_bytes(b"new")
            self.assertNotEqual(server.revision, web.service_revision())
            self.assertEqual(server.static["/app.js"][0], b"original")


class IncidentTests(unittest.TestCase):
    def setUp(self):
        HOME.mkdir(parents=True, exist_ok=True)

    def test_report_check_remains_exact_and_explains_mismatches(self):
        with TemporaryDirectory(dir=HOME) as scratch:
            root = Path(scratch)
            spec = {"stages":[{"id":"preflight"},{"id":"g3-direct"}]}
            spec["sha256"] = identity(spec)
            row = dict(id=timing.INCIDENT_JOB, state="interrupted", stage=1, token="attempt")
            write(root/"task.json",spec)
            write(root/"report.json",{"original":True})
            audit = root/"incident.json"
            proof = dict(source=timing.INCIDENT_JOB, key=timing.CONTINUATION_JOB, token="attempt",
                         task_sha256=spec["sha256"], report_sha256=checksum(root/"report.json"),
                         completed=["preflight"], timing={"confirmed_seconds":123})
            write(audit,proof)
            with patch.object(timing,"INCIDENT",audit):
                self.assertEqual(timing.audited_timing(row,root,spec), proof["timing"])
                self.assertIn("令牌", timing.incident_status(row | {"token":"different"},root,spec)[1])
                self.assertIn("中断阶段", timing.incident_status(row | {"stage":0},root,spec)[1])
                write(root/"report.json",{"original":True,"different":True})
                self.assertIsNone(timing.audited_timing(row,root,spec))
                self.assertIn("report.json SHA-256",timing.incident_status(row,root,spec)[1])

    def test_blocked_plan_remains_visible(self):
        with TemporaryDirectory(dir=HOME) as scratch:
            templates=Path(scratch)
            panel=backend.Backend(HOME,templates)
            with (patch.object(backend, "CONFIGS", templates), patch.object(
                  backend, "offer", side_effect=ValueError("长任务报告哈希不一致"))):
                item, = panel.plans(None)
                self.assertEqual(item["spec"]["id"],timing.CONTINUATION_JOB)
                self.assertEqual(item["reasons"],["长任务报告哈希不一致"])
                with self.assertRaisesRegex(ValueError,"报告哈希"):
                    panel.allowed_plan(None,timing.CONTINUATION_JOB)


if __name__ == "__main__":
    unittest.main()
