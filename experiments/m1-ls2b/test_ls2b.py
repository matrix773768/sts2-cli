from contextlib import contextmanager
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
from threading import Event
from time import monotonic
import unittest

import report_analysis as analyze
from campaign import HERE, binding, cases_for, read
from execute import portfolio
import engine
import learning
from spec import canonical, context, digest, edits, feedback, generate
from space import check_splits, inventory
import store

EVIDENCE = HERE/"evidence"


def manifest(name):
    return store.unpack((EVIDENCE/f"{name}-manifest.audit.json.gz").read_bytes())


class Evidence(unittest.TestCase):
    def test_disjoint_roots_budgets_and_training_lineage(self):
        cases = []
        for phase in ("pilot", "development", "report"):
            m = manifest(phase)
            for job in m["jobs"]:
                case = job["case"]
                cases.append(case)
                profiles = case["schedule"]["profiles"]
                self.assertEqual(job["reserved"], sum(p[2] for p in profiles))
                if phase == "report":
                    for cap in m["config"]["budgets"]:
                        self.assertEqual({p[0] for p in profiles if p[2] == cap}, set(analyze.ARMS))
                    self.assertEqual(digest(m["config"]["model"]), read(EVIDENCE/"summary.json")["model"])
        check_splits(cases)
        self.assertEqual(len(set(c["recipe"] for c in cases)), len(cases))
        self.assertEqual(len(set(c["id"] for c in cases)), len(cases))
        model = read(EVIDENCE/"model.json")
        self.assertTrue(set(model["roots"]) <= {j["id"] for j in manifest("development")["jobs"]})
        with self.assertRaises(ValueError):
            learning.fit(analyze.fit_rows(EVIDENCE/"report-public.jsonl.gz"), model["binding"])
        rebuilt = learning.fit(analyze.fit_rows(EVIDENCE/"development-public.jsonl.gz"), model["binding"])
        self.assertEqual(model["supervision"], rebuilt["supervision"])
        learning.np.testing.assert_allclose(model["coefficients"], rebuilt["coefficients"], rtol=1e-11, atol=1e-12)

    def test_public_features_and_distinct_terminal_feedback(self):
        with gzip.open(EVIDENCE/"development-public.jsonl.gz", "rt") as stream:
            pub = json.loads(stream.readline())["public_context"]
        before = context(pub)
        poisoned = deepcopy(pub)
        poisoned.update(rng="forbidden", exact="forbidden", next_draw=["injected"], audit={"locked": {}})
        self.assertEqual(generate(before), generate(context(poisoned)))
        self.assertGreater(before["missing"], 0)
        candidate = generate(before)[0]
        same = candidate | dict(setup_turns=0)
        self.assertEqual(canonical(same), canonical(same | dict(opening={}, finish_pct=88)))
        choices = {digest(s) for s in generate(before)}
        self.assertGreater(len(choices), 4)
        self.assertEqual(edits(candidate, feedback(dict(status="unsupported")), before), [])
        for reason in ("death", "action_cap", "transition_cap", "wall_cap", "unsupported", "verification_failed"):
            self.assertEqual(feedback(dict(status=reason))["observed"], reason)

    def test_observed_edit_cost_and_public_export(self):
        summary = read(EVIDENCE/"summary.json")
        for phase in ("development", "report"):
            import hashlib
            path = EVIDENCE/f"{phase}-public.jsonl.gz"
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), summary["shards"][path.name])
            count = 0
            for _, features, label in analyze.training_examples(path):
                self.assertNotIn("trace", features)
                self.assertNotIn("root", features)
                self.assertIn("status", label)
                count += 1
            self.assertEqual(count, summary[phase]["exported_attempts"])
        for w in read(EVIDENCE/"repair-witnesses.json"):
            old, child = w["parent"], w["repaired"]
            self.assertEqual(old["strategy_hash"], child["parent_strategy"])
            self.assertEqual(child["verification"], len(child["path"]))
            self.assertTrue(analyze.differs(old["path"], child["path"]))
            self.assertGreater(w["locked"]["hp"], 0)
            self.assertGreaterEqual(w["first_replays"], old["transitions"]+child["transitions"]+child["verification"])
        self.assertGreater(summary["paired"]["learned-256"]["learned_first_action_sequence_changed"], 0)
        self.assertFalse(analyze.differs(["a"], ["a", "b"]))


@unittest.skipUnless(os.environ.get("STS2_LS2B_NATIVE"), "Set STS2_LS2B_NATIVE to a native test output directory")
class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ["STS2_LS2B_NATIVE"]).resolve()
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.new = binding(cls.out)
        cls.catalog = engine.catalog(cls.out, cls.new)
        cls.cases = {c["id"]: c for c in cases_for(cls.catalog, read(HERE/"formal.json"), "report")}

    @contextmanager
    def opened(self, case, versions):
        with engine.root(self.out, case, versions, monotonic()+60, Event()) as (g, obs, ident, exact, *_):
            pub, *_ = engine.public_projection(obs, ident["resources"], case["spec"]["character"], inventory(self.catalog))
            yield g, pub, exact

    def test_legacy_host_and_disabled_spec_identical(self):
        for rid, status in (("f31b74dd32fe667860ec", "transition_cap"),
                            ("6e133b9f529756bc720f", "qualified_win")):
            actual = []
            for host in ("m1-ls2a-build", "m1-ls2b-build"):
                v = engine.ls1.setup(self.out, host=host)
                with self.opened(self.cases[rid], v) as (g, _, exact):
                    result = engine.ls1.search(g, 128, 256)
                    self.assertEqual(result["status"], status)
                    actual.append((exact, engine.ls1.semantic(result)))
            self.assertEqual(*actual)

    def test_repair_reexecutes_from_cold_root_and_rejects_unknown_fields(self):
        witness = read(EVIDENCE/"repair-witnesses.json")[0]
        case = self.cases[witness["root"]]
        model = read(EVIDENCE/"model.json")
        def replay():
            with self.opened(case, self.new) as (g, pub, exact):
                row = portfolio(g, 256, "learned", pub, model)
                self.assertTrue(analyze.eligible(row))
                repaired = row["attempts"][-1]
                self.assertEqual(witness["repaired"]["route_key"], repaired["route_key"])
                self.assertEqual(row["locked"], witness["locked"])
                self.assertGreater(len({step["phase"] for step in repaired["trace"]}), 1)
                return exact, row["transitions"], repaired["path"], row["locked_key"]
        first = replay()
        other = self.cases["f31b74dd32fe667860ec"]
        with self.opened(other, self.new) as (g, pub, _):
            candidate = generate(context(pub))[0]
            with self.assertRaises(engine.RPC_ERROR):
                engine.ls1.request(g, "i1_f3b", 16, strategy_spec=candidate | {"private_rng": 42})
        self.assertEqual(first, replay())


if __name__ == "__main__":
    unittest.main()
