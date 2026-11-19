import unittest
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import numpy as np

import offline_data as data
import offline_cv as cv


class OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = data.load()
        cls.config = data.read(data.HERE / "protocol.json")

    def test_training_only_archive_and_folds(self):
        allowed = {"artifact-hashes.json", "data.json.gz", "ledger.json.gz", "protocol.json"}
        original = Path.read_bytes

        def guarded(path):
            if path.parent == data.BASE:
                self.assertIn(path.name, allowed)
            return original(path)

        with patch.object(Path, "read_bytes", guarded):
            self.assertEqual(data.load(), self.rows)
        self.assertEqual(data.digest(self.rows), self.config["records_sha256"])
        folds = data.fold_plan(self.rows)
        self.assertEqual(folds, self.config["folds"])
        self.assertEqual(len({i for f in folds for i in f["held_ids"]}), 320)
        for fold in folds:
            held = set(fold["held_ids"])
            self.assertEqual(len(held), 64)
            self.assertEqual({r["audit"]["template"] for r in self.rows if r["audit"]["id"] in held},
                             set(fold["held_groups"]))
            self.assertFalse(set(fold["held_groups"]) &
                             {r["audit"]["template"] for r in self.rows if r["audit"]["id"] not in held})

    def test_public_inputs_and_fold_prior(self):
        row = self.rows[0]
        catalog = data.load_catalog()
        labels = np.array([0, 1])
        table = cv.prior([row, row], labels, 1)
        np.testing.assert_allclose(table[cv.stratum(row)], [2/5, 2/5, 1/5])
        for mode in cv.parent.MODES:
            x = cv.parent.stacked([row], mode, catalog, 128)
            altered = dict(row, audit={"id": "forbidden"}, status="truncated", label=2,
                           winning_hp=1000)
            y = cv.parent.stacked([altered], mode, catalog, 128)
            for a, b in zip(x, y):
                np.testing.assert_array_equal(a, b)

    def test_softmax_and_metric(self):
        p = cv.softmax(np.array([[1000., 1000., 1000.], [-1000., -999., -998.]]))
        np.testing.assert_allclose(p.sum(axis=1), 1)
        self.assertAlmostEqual(cv.metrics(np.array([0]), p[:1])["brier"], 2/3)
        self.assertAlmostEqual(cv.metrics(np.array([0]), p[:1])["log_loss"], np.log(3))

    def test_gradients_capacity_and_repeat(self):
        catalog = data.load_catalog()
        y = np.array([0, 1, 2, 2])
        counts = {}
        cfg = dict(self.config, epochs=3)
        for mode in cv.parent.MODES:
            x = cv.parent.stacked(self.rows[:4], mode, catalog, 128)
            p = cv.init(x, 12, 17)
            counts[mode] = sum(a.size for a in p.values())
            grad = cv.gradients(p, x, y, cfg["l2"])

            def loss():
                probs = cv.forward(p, x)[0]
                return cv.metrics(y, probs)["log_loss"] + cfg["l2"]/2 * sum(
                    np.sum(a*a) for k, a in p.items() if k.endswith("_w"))

            for key, array in p.items():
                idx = (0,) * array.ndim
                before = array[idx]
                array[idx] = before + 1e-5
                hi = loss()
                array[idx] = before - 1e-5
                lo = loss()
                array[idx] = before
                self.assertAlmostEqual((hi - lo)/2e-5, grad[key][idx], places=6)
            a = cv.fit(x, y, cfg, 17, perf_counter()+10)
            b = cv.fit(x, y, cfg, 17, perf_counter()+10)
            for key in a:
                np.testing.assert_array_equal(a[key], b[key])
        self.assertEqual(counts, {"statistics": 117, "identity": 1887, "mechanics": 1887})

    def test_published_predictions_use_fold_prior(self):
        records = data.read(data.HERE / "results/predictions.json")
        by_id = {r["id"]: r for r in records}
        self.assertEqual(len(records), len(by_id))
        for fold in self.config["folds"]:
            held = set(fold["held_ids"])
            train = [r for r in self.rows if r["audit"]["id"] not in held]
            table = cv.prior(train, [data.LABELS[r["status"]] for r in train], 1)
            for row in self.rows:
                root = row["audit"]["id"]
                if root in held:
                    self.assertEqual(by_id[root]["label"], data.LABELS[row["status"]])
                    np.testing.assert_allclose(by_id[root]["probabilities"]["prior"], table[cv.stratum(row)])


if __name__ == "__main__":
    unittest.main()
