"""Targeted tests for the frozen manifest, features, learner and stage locks."""
from collections import Counter
from pathlib import Path
import tempfile
from time import perf_counter
import unittest

import numpy as np

import learning
from delivery import factorial_bounds
from rollout import text_hash, training_qualification, verify_model_lock
from study_design import HERE, digest, load_catalog, manifest, read, save


class StudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = read(HERE / "protocol.json")
        cls.cases = read(HERE / "manifest.json")
        cls.catalog = load_catalog()

    def test_exact_manifest_and_budget(self):
        self.assertEqual(manifest(), self.cases)
        self.assertEqual(digest(self.cases), self.protocol["manifest_sha256"])
        self.assertEqual(len(self.cases) + self.protocol["audit_roots"], self.protocol["execution_budget"])
        pairs = {}
        for item in self.cases:
            case = item["case"]
            self.assertEqual(digest(case["spec"]), case["spec_sha256"])
            self.assertEqual(len(case["spec"]["deck"]), 15)
            pairs.setdefault(case["pair"], []).append(case)
        for cases in pairs.values():
            self.assertEqual(len({case["spec"]["seed"] for case in cases}), 1)
            self.assertEqual(len({case["cohort"] for case in cases}), 1)
            self.assertEqual({(c["slot_a"], c["slot_b"]) for c in cases}, {(0, 0), (0, 1), (1, 0), (1, 1)})

    def test_features_are_multisets_without_audit_fields(self):
        original = self.cases[3]["case"]["spec"]
        modified = dict(original, seed="SECRET", id="SECRET", label=1, rng="SECRET", deck_sha256="SECRET",
                        deck=list(reversed(original["deck"])))
        for mode in learning.MODES:
            x = learning.encode(original, mode, self.catalog, 128)
            y = learning.encode(modified, mode, self.catalog, 128)
            self.assertTrue(all(np.array_equal(a, b) for a, b in zip(x, y)))
            self.assertFalse(np.array_equal(x[0], learning.encode(dict(original, hp=18), mode,
                                                                  self.catalog, 128)[0]))
        unknown = dict(original, deck=[dict(id="UNQUALIFIED_TEST", upgrade=0)])
        features = learning.encode(unknown, "mechanics", self.catalog, 128)[1]
        known = dict(original, deck=[original["deck"][0]])
        self.assertFalse(np.array_equal(features, learning.encode(known, "mechanics", self.catalog, 128)[1]))
        variant = dict(known, deck=[dict(known["deck"][0], upgrade=1)])
        for mode in ("identity", "mechanics"):
            self.assertFalse(np.array_equal(learning.encode(known, mode, self.catalog, 128)[1],
                                            learning.encode(variant, mode, self.catalog, 128)[1]))

    def test_parameter_matching_and_gradient(self):
        records = [{"input": case["case"]["spec"]} for case in self.cases[:4]]
        sizes = {}
        for mode in learning.MODES:
            inputs = learning.stacked(records, mode, self.catalog, 128)
            params = learning.init(inputs, 12, 17)
            sizes[mode] = sum(v.size for v in params.values())
            labels = np.array([0, 1, 0, 1])
            gradients = learning.gradients(params, inputs, labels, .002)
            key, index = ("card_w", (0, 0)) if "card_w" in params else ("out_w", (0,))

            def loss():
                p = learning.forward(params, inputs)[0]
                return (-np.mean(labels * np.log(p) + (1-labels) * np.log1p(-p))
                        + .001 * sum(np.sum(v**2) for k, v in params.items() if k.endswith("_w")))

            params[key][index] += 1e-5
            upper = loss()
            params[key][index] -= 2e-5
            lower = loss()
            self.assertAlmostEqual(gradients[key][index], (upper-lower)/2e-5, places=6)
        self.assertEqual(sizes["identity"], sizes["mechanics"])

    def test_factorial_respects_pair_and_missing_label(self):
        records = [{"audit": {k: v for k, v in item["case"].items() if k != "spec"},
                    "input": item["case"]["spec"], "label": label}
                   for item, label in zip(self.cases[:4], [0, 0, 0, 1])]
        result, = learning.factorial(records, [.1, .2, .3, .5])
        self.assertEqual(result["observed"], 1)
        self.assertAlmostEqual(result["predicted"], .1)
        records[0]["label"] = None
        self.assertEqual(learning.factorial(records, [.1, .2, .3, .5]), [])

    def test_bound_missing_factorial_outcomes(self):
        bounds = factorial_bounds({
            ("train/strength", 0): {(0, 0): 0, (1, 0): 0, (0, 1): 1, (1, 1): 1},
            ("train/strength", 1): {(0, 0): None, (1, 0): None, (0, 1): 0, (1, 1): 1},
        })["train/strength"]
        self.assertEqual(dict(blocks=2, complete=1, complete_mean=0, lower=0, upper=1), bounds)

    def test_bounded_fit_on_synthetic_labels(self):
        protocol = self.protocol["training"]
        for mode in learning.MODES:
            records = [{"input": case["case"]["spec"]} for case in self.cases[:4]]
            for i, row in enumerate(records):
                row["input"] = dict(row["input"], hp=10 if i < 2 else 80)
            inputs = learning.stacked(records, mode, self.catalog, protocol["card_dim"])
            labels = np.array([0, 0, 1, 1])
            old = learning.forward(learning.init(inputs, protocol["hidden"], 17), inputs)[0]
            checkpoints = dict(learning.fit(inputs, labels, protocol, 17, perf_counter() + 10))
            self.assertEqual(list(checkpoints), protocol["epochs"])
            new = learning.forward(checkpoints[180], inputs)[0]
            self.assertLess(np.mean((new - labels)**2), np.mean((old - labels)**2))

    def test_frozen_feedback_gate_uses_missing_separately(self):
        stop = self.protocol["stop"]
        counts = dict(predicted_win=240, death=32, truncated=48)
        self.assertTrue(training_qualification(counts, 320, stop)["passed"])
        counts.update(death=31, truncated=49)
        self.assertFalse(training_qualification(counts, 320, stop)["passed"])
        counts.update(predicted_win=300, death=20, truncated=0)
        self.assertFalse(training_qualification(counts, 320, stop)["passed"])

    def test_report_model_lock(self):
        with tempfile.TemporaryDirectory(dir=HERE.parents[1] / "logs") as directory:
            output = Path(directory)
            with self.assertRaises(FileNotFoundError):
                verify_model_lock(output)
            model = dict(protocol_sha256=digest(self.protocol),
                         model_code_sha256=text_hash(HERE / "learning.py"))
            save(output / "models.json", dict(model, sha256=digest(model)))
            verify_model_lock(output)
            save(output / "models.json", dict(model, sha256="invalid"))
            with self.assertRaises(ValueError):
                verify_model_lock(output)


if __name__ == "__main__":
    unittest.main()
