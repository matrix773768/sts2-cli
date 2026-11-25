"""Loopback authorization and INF2 plan admission tests."""

from contextlib import closing
from http.client import HTTPConnection
import json
import os
import sqlite3
import subprocess
import sys
from threading import Event, Thread
from time import monotonic, sleep
import unittest
from unittest.mock import patch
import uuid

from tools.training_manager.common import HOME, ROOT, checksum, read, write
from tools.training_manager.dashboard.__main__ import Dashboard
from tools.training_manager.dashboard.backend import INITIAL, Backend, contained, review_gate
from tools.training_manager.ledger import identity
from tools.training_manager.manager import Manager


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.home = HOME / ("inf2-test-" + uuid.uuid4().hex[:10])
        self.manager = Manager(self.home)
        self.addCleanup(self.manager.db.close)
        self.templates = self.home / "templates"
        self.templates.mkdir()
        self.spec = self.template()
        write(self.templates / "fixture.json", self.spec)
        self.server = Dashboard(self.home, 0)
        self.server.backend = Backend(self.home, self.templates)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.thread.join(10)
        self.server.server_close()

    def template(self):
        return dict(id="fixture", name="INF2 fixture", type="simulation", cwd=".",
                    mode="Any", max_retries=0, python=sys.executable, inputs=[],
                    output=(self.home/"jobs/fixture").relative_to(ROOT).as_posix(),
                    stages=[dict(id="work", depends_on=[], args=["tests/inf1_task_fixture.py", "{work}", "3"],
                                 gpu=False, heavy=False, workers=1, resume="checkpoint", boundary="committed")])

    def request(self, path, body=None, cookie=None, csrf=None, **overrides):
        headers = {"Host": self.server.host, "Origin": self.server.url}
        headers.update(overrides)
        if csrf:
            headers["X-INF2-CSRF"] = csrf
        if cookie:
            headers["Cookie"] = cookie
        if body is not None:
            headers["Content-Type"] = "application/json"
        with closing(HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)) as connection:
            connection.request("GET" if body is None else "POST", path,
                               None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read()), response.getheader("Set-Cookie")

    def authorize(self):
        status, data, cookie = self.request("/api/session", {"proof": self.server.bootstrap})
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly; SameSite=Strict", cookie)
        return {"cookie":cookie.split(";")[0], "csrf":data["csrf"]}

    def test_origin_host_session_and_csrf(self):
        self.assertEqual(self.request("/health", Host="rebound.invalid")[0], 403)
        self.assertEqual(self.request("/api/state")[0], 401)
        self.assertEqual(self.request("/api/session", {"proof":"unapproved"})[0], 403)
        auth = self.authorize()
        self.assertEqual(self.request("/api/action/mode", {"mode":"Full"}, **auth, Origin="https://elsewhere.invalid")[0], 403)
        self.assertEqual(self.request("/api/action/mode", {"mode":"Full"}, **auth, **{"Sec-Fetch-Site":"cross-site"})[0], 403)
        self.assertEqual(self.request("/api/action/mode", {"mode":"Full"}, cookie=auth["cookie"])[0], 403)
        self.assertEqual(self.request("/api/action/mode", {"mode":"Full"}, csrf=auth["csrf"])[0], 403)
        self.assertIsNone(self.manager.get_control("mode"))
        self.assertEqual(self.request("/api/action/mode", {"mode":"Full"}, **auth)[1]["mode"], "Full")

    def test_read_review_freeze_submit_and_duplicate(self):
        auth = self.authorize()
        other = self.authorize()
        self.assertEqual(self.request("/api/plans", **auth)[0], 200)
        self.assertEqual(self.manager.rows(), [])
        self.assertIsNone(self.manager.get_control("enabled"))
        frozen = self.request("/api/action/freeze", {"id":"fixture"}, **auth)[1]
        self.assertEqual(self.manager.rows(), [])
        submit = {"draft":frozen["draft"], "sha256":frozen["spec"]["sha256"]}
        self.assertEqual(self.request("/api/action/submit", submit, **other)[0], 409)
        self.assertEqual(self.request("/api/action/submit", submit | {"sha256":"invalid"}, **auth)[0], 409)
        write(self.templates/"fixture.json", self.spec | {"name":"changed"})
        self.assertEqual(self.request("/api/action/submit", submit, **auth)[0], 409)
        write(self.templates/"fixture.json", self.spec)
        self.assertEqual(self.request("/api/action/submit", submit, **auth)[0], 200)
        self.assertEqual(self.manager.job("fixture")["state"], "queued")
        self.assertEqual(self.request("/api/action/submit", submit, **auth)[0], 409)
        self.assertEqual(self.request("/api/action/freeze", {"id":"fixture"}, **auth)[0], 409)
        self.assertEqual(self.request("/api/file?id=fixture&name=task.json", **auth)[0], 200)
        for path in ("../templates/fixture.json", "../../settings.json", "report.json/../task.json"):
            self.assertEqual(self.request("/api/file?id=fixture&name=" + path, **auth)[0], 409)

    def test_conflicting_output_and_control_state(self):
        auth = self.authorize()
        output = self.home/"jobs/fixture"
        output.mkdir(parents=True)
        sentinel = output/"keep.json"
        write(sentinel, {"keep": True})
        result = self.request("/api/action/freeze", {"id":"fixture"}, **auth)
        self.assertEqual(result[0], 409)
        self.assertIn("输出目录已经存在", result[1]["error"])
        self.assertEqual(read(sentinel), {"keep": True})
        self.assertEqual(self.request("/api/action/stop-all", {}, **auth)[1]["enabled"], False)
        self.assertEqual(self.request("/api/action/enable", {}, **auth)[1]["enabled"], True)
        self.assertEqual(self.request("/api/action/settings", {"min_ram_mb":0}, **auth)[0], 409)
        self.assertEqual(self.request("/api/action/settings", {"idle_seconds":120}, **auth)[0], 200)
        self.assertEqual(read(self.home/"settings.json")["idle_seconds"], 120)

    def test_redirected_path(self):
        output = self.home/"aliases"
        output.mkdir()
        alias = output/"outside"
        if os.name == "nt":
            created = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                                      "New-Item -ItemType Junction -Path $env:INF2_TEST_ALIAS -Target $env:INF2_TEST_TARGET"],
                                     env=os.environ | {"INF2_TEST_ALIAS":str(alias),
                                                       "INF2_TEST_TARGET":str(self.templates)}, capture_output=True)
            self.assertEqual(created.returncode, 0, created.stderr)
        else:
            alias.symlink_to(self.templates, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "已审核"):
            contained(output, alias/"fixture.json")

    @unittest.skipUnless(os.name == "nt", "Requires INF1 Windows supervision")
    def test_atomic_progress_waits_for_a_short_lived_reader(self):
        progress = self.home/"progress.json"
        write(progress, {"done":1})
        opened = Event()
        previous = []

        def read_while_open():
            with progress.open("rb") as stream:
                opened.set()
                sleep(.08)
                previous.append(json.load(stream))

        reader = Thread(target=read_while_open)
        reader.start()
        self.assertTrue(opened.wait(2))
        try:
            write(progress, {"done":2})
        finally:
            reader.join(2)
        self.assertEqual(previous, [{"done":1}])
        self.assertEqual(read(progress), {"done":2})

    def test_stop_all_waits_for_an_active_checkpoint(self):
        auth = self.authorize()
        stage = self.spec["stages"][0]
        stage["args"][-1] = "60"
        write(self.templates/"fixture.json", self.spec)
        draft = self.request("/api/action/freeze", {"id":"fixture"}, **auth)[1]
        self.assertEqual(self.request("/api/action/submit",
                                      {"draft":draft["draft"],"sha256":draft["spec"]["sha256"]}, **auth)[0], 200)
        self.request("/api/action/mode", {"mode":"Full"}, **auth)
        checkpoint = self.home/"jobs/fixture/work/units.json"
        snapshot = dict(ram_mb=4096,disk_mb=4096,ac=True,idle_seconds=900,gpus=None)

        def wait_until(condition):
            limit = monotonic() + 20
            while monotonic() < limit:
                self.manager.step(lambda *_: snapshot)
                if condition():
                    return
                sleep(.08)
            self.fail(dict(self.manager.job("fixture")))

        try:
            wait_until(lambda: len(read(checkpoint, [])) >= 2)
            self.assertEqual(self.request("/api/action/stop-all", {}, **auth)[0], 200)
            self.assertEqual(self.manager.job("fixture")["state"], "pausing")
            wait_until(lambda: self.manager.job("fixture")["state"] == "paused")
            committed = read(checkpoint)
            self.assertTrue(2 <= len(committed) < 60)
            self.assertEqual(committed, list(range(len(committed))))
            self.assertFalse(self.manager.get_control("enabled"))
        finally:
            for child in self.manager.children:
                child.wait(timeout=15)

    def test_curriculum_requires_model_bound_gate_and_completed_runs(self):
        self.assertIn("尚未提交", review_gate(self.manager))
        output = self.home/"jobs"/INITIAL
        output.mkdir(parents=True)
        stage_ids = ("initial","development","gate","complex-baseline","complex-development")
        spec = self.spec | {"id": INITIAL, "output": output.relative_to(ROOT).as_posix(),
                            "stages":[{"id":name} for name in stage_ids]}
        write(output/"task.json", spec)
        self.manager.db.execute("INSERT INTO jobs (id,spec,state,stage,submitted) VALUES (?,?,?,?,0)",
                                (INITIAL,json.dumps(spec),"failed",len(stage_ids)))
        self.assertIn("未成功", review_gate(self.manager))
        self.manager.update(self.manager.job(INITIAL), state="completed")
        (output/"gate").mkdir()
        gate = output/"gate/gate.json"
        write(gate, {"passed":False})
        self.assertIn("未通过", review_gate(self.manager))
        write(gate, {"passed":True})
        self.assertIn("退出记录", review_gate(self.manager))
        for index, _ in enumerate(stage_ids):
            self.manager.db.execute("INSERT INTO runs(token,job,stage,profile,launched,ended,result,command) "
                                    "VALUES (?,?,?,'Full',0,1,?,'[]')",
                                    (str(index), INITIAL, index,
                                     json.dumps({"state":"completed","exit_code":0,"started":0,"ended":1})))
        model = output/"initial/best.pt"
        model.parent.mkdir()
        model.write_bytes(b"test-model")
        dc1 = self.home/"reference"
        reference = self.ledger(dc1/"evaluation/development/D2/results.sqlite", "reference", 512, "development")
        candidate = self.ledger(output/"development/ledger/results.sqlite", checksum(model),512,"development")
        self.ledger(output/"complex-baseline/ledger/results.sqlite","reference",12,"complex_development")
        self.ledger(output/"complex-development/ledger/results.sqlite",checksum(model),12,"complex_development")
        evidence = {"reference":identity(reference), "candidate":identity(candidate)}
        comparison = {"paired":512,"joint_complete":512,"win_delta":0,"death_delta":0}
        with patch("tools.training_manager.dashboard.backend.DC1", dc1):
            write(gate, {"passed":True,"comparison":comparison})
            self.assertIn("未绑定", review_gate(self.manager))
            write(gate, {"passed":True,"comparison":comparison,"evidence":evidence})
            self.assertIsNone(review_gate(self.manager))
            model.write_bytes(b"changed")
            self.assertIn("身份不一致", review_gate(self.manager))

    def ledger(self, path, model, count, purpose):
        path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("CREATE TABLE contract(sha TEXT,json BLOB); CREATE TABLE results(ordinal INT,sha TEXT);")
            contract = dict(definition={"model":model}, manifest="manifest", purpose=purpose)
            db.execute("INSERT INTO contract VALUES ('contract',?)", (json.dumps(contract),))
            db.executemany("INSERT INTO results VALUES (?,?)", [(i,str(i)) for i in range(count)])
        return path


if __name__ == "__main__":
    unittest.main()
