import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import night


class NightTests(unittest.TestCase):
    def test_frozen_plan_and_slots(self):
        plan=night.ROOT/"configs/training_jobs/dc2b-night1.json"
        with tempfile.TemporaryDirectory(dir=night.ROOT/"logs") as tmp:
            generated=Path(tmp)/"night.json"
            night.make(generated)
            self.assertEqual(plan.read_bytes(),generated.read_bytes())
        data=json.loads(plan.read_bytes())
        seen=set()
        for stage in data["stages"]:
            self.assertNotIn(stage["id"],seen)
            self.assertLessEqual(set(stage["depends_on"]),seen)
            self.assertFalse(any("challenge.json" in arg for arg in stage["args"]))
            seen.add(stage["id"])
        self.assertIn("g12-audit",seen)
        self.assertEqual(data["budget_seconds"],28800)

    def test_hf1_plan_keeps_budget_and_uses_independent_namespace(self):
        paths=night.ROOT/"configs/training_jobs"
        base=json.loads((paths/"dc2b-night1.json").read_bytes())
        hf=paths/"dc2b-night1-hf1.json"
        data=json.loads(hf.read_bytes())
        with tempfile.TemporaryDirectory(dir=night.ROOT/"logs") as tmp:
            path=Path(tmp)/"hf1.json"
            night.make(path,data["id"])
            self.assertEqual(path.read_bytes(),hf.read_bytes())
        self.assertEqual(base["limits"],data["limits"])
        self.assertEqual(base["budget_seconds"],data["budget_seconds"])
        self.assertNotEqual(base["output"],data["output"])
        for stage in data["stages"]:
            args=stage["args"]
            if "produce" in args:
                self.assertEqual(args[args.index("--night-namespace")+1],data["id"])

    def test_restore_committed_files_and_relocate_progress(self):
        with tempfile.TemporaryDirectory(dir=night.ROOT/"logs") as tmp:
            root=Path(tmp).resolve()
            jobs=root/"logs/inf1/jobs"
            old,new=jobs/"dc2b-night1-hf1",jobs/"dc2b-night1-hf1-r1"
            stage=old/"g1-direct"
            ledger=stage/"ledger"
            ledger.mkdir(parents=True)
            (stage/"roots.json").write_text("{}")
            (stage/"request.json").write_text("{}")
            (ledger/"results.sqlite").write_bytes(b"committed results")
            (stage/"progress.json").write_text(json.dumps({"checkpoint":str(ledger/"results.sqlite")}))
            (old/"report.json").write_text(json.dumps(dict(id=old.name,state="cancelled",reason="budget")))
            with patch.object(night,"ROOT",root):
                night.restore(old,new)
                night.restore(old,new)
            self.assertEqual((new/"g1-direct/ledger/results.sqlite").read_bytes(),b"committed results")
            progress=json.loads((new/"g1-direct/progress.json").read_bytes())
            self.assertEqual(Path(progress["checkpoint"]),new/"g1-direct/ledger/results.sqlite")
            self.assertFalse((new/"g1-direct/request.json").exists())


if __name__=="__main__":
    unittest.main()
