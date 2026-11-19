"""Exercise admission, transactional recovery and the isolated native differential."""
from contextlib import closing
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from engine import public_projection
from export_data import safe_candidate, semantic_cell
from pipeline import schedule, validate_config
from space import HERE, check_splits, digest, read, synthetic
import store


class StoreTests(unittest.TestCase):
    def test_abrupt_owner_exit_recovery_and_exact_cache(self):
        job = {"id": "sample", "cache": digest(["version", "root", "budget"]), "reserved": 96}
        plan = {"name": "first", "version": 1}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "search.sqlite"
            with closing(store.open_store(path)) as db:
                store.register(db, plan, [job])
                with self.assertRaises(ValueError):
                    store.register(db, plan | {"version": 2}, [job])
            child = f"""import os, sys
sys.path.insert(0, {str(HERE)!r})
from store import open_store, reserve
db = open_store({str(path)!r})
reserve(db, "first", "sample", 96)
os._exit(7)
"""
            self.assertEqual(subprocess.run([sys.executable, "-c", child]).returncode, 7)
            with closing(store.open_store(path)) as db:
                self.assertEqual(store.recover(db, "first", 2), 1)
                self.assertEqual(store.charged(db, "first"), 96)
                self.assertEqual(store.pending(db, "first"), [("sample", job["cache"], 96)])
                attempt = store.reserve(db, "first", "sample", 96)
                actual = {"outcome": "complete", "exact": "root", "cells": [{"outcome": {"transitions": 29}}]}
                self.assertEqual(store.finish(db, "first", job, attempt, actual, 2), "done")
                self.assertEqual(store.charged(db, "first"), 125)
                self.assertEqual(store.pending(db, "first"), [])
                store.register(db, {"name": "second"}, [job])
                self.assertEqual(store.payload(db, job["cache"]), actual)
                store.reserve(db, "second", "sample", 96, hit=True)
                self.assertEqual(list(store.results(db, "second")), [("sample", actual)])
                self.assertEqual(store.charged(db, "second"), 0)
                different = job | {"cache": digest(["other version", "root", "budget"])}
                self.assertIsNone(store.payload(db, different["cache"]))
                with db:
                    db.execute("UPDATE payloads SET sha='tampered'")
                with self.assertRaisesRegex(ValueError, "checksum"):
                    store.payload(db, job["cache"])

    def test_unknown_cost_is_conservatively_charged_and_retry_is_bounded(self):
        with TemporaryDirectory() as directory, closing(
                store.open_store(Path(directory) / "retry.sqlite")) as db:
            job = {"id": "sample", "cache": "cached-exact-key", "reserved": 64}
            store.register(db, {"name": "p"}, [job])
            timeout = {"outcome": "transient", "cells": [{"outcome": {"transitions": 8}}]}
            for index, expected in enumerate(("pending", "failed"), 1):
                self.assertEqual(store.reserve(db, "p", "sample", 64), index)
                self.assertEqual(store.finish(db, "p", job, index, timeout, 2), expected)
            self.assertEqual(store.charged(db, "p"), 128)
            self.assertEqual(store.pending(db, "p"), [])
            self.assertEqual(list(store.results(db, "p")), [("sample", timeout)])
            self.assertIsNone(store.payload(db, job["cache"]))


class Contracts(unittest.TestCase):
    def test_public_projection_ignores_private_fields_and_retains_missing_semantics(self):
        card = dict(id="CARD.OUT_OF_CATALOG", upgraded=False)
        public = dict(decision="combat_play", context={"act": 1}, round=1, energy=3, max_energy=3,
                      draw_pile_count=6, discard_pile_count=0, enemies=[], hand=[],
                      player=dict(hp=40, max_hp=80, gold=99, block=0, deck_size=1, deck=[card],
                                  potions=[], relics=[]))
        resource = dict(potions=[None, None], relics=[])
        known = public_projection(public, resource, "Defect", {})
        injected = deepcopy(public)
        for row in (injected, injected["player"], injected["player"]["deck"][0]):
            row.update(future="hidden", rng={"seed": "private"}, root_stamp="stamp", draw=["secret"])
        self.assertEqual(known, public_projection(injected, resource | {"live": "private"}, "Defect", {}))
        features, gaps, coverage, _ = known
        self.assertIn("card_mechanism_partial", gaps)
        self.assertEqual(coverage, {"OUT_OF_CATALOG": "unknown"})
        self.assertEqual(features["mechanics_deck"]["cards"][0]["card"]["effects"][0]["kind"],
                         "UnsupportedEffect")

    def test_group_guards_include_source_independent_correlations(self):
        common = dict(source="synthetic", spec={"encounter": "A"})
        for field in ("history", "seed", "pair", "family", "recipe", "exact"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                check_splits([common | {"split": "train", field: "same"},
                              common | {"split": "test", field: "same"}])
        with self.assertRaisesRegex(ValueError, "encounter"):
            check_splits([common | {"split": "train"}, common | {"split": "test"}])

    def test_cost_budget_is_not_a_proof_of_defeat(self):
        row = dict(tier="candidate", route_risks=[], attempts=[
            dict(status="truncated", detail="wall_cap", verified_win=False)])
        self.assertIsNone(safe_candidate(row))
        self.assertEqual(safe_candidate(row | {"attempts": [
            dict(status="truncated", detail="transition_cap", verified_win=False)]}), 0)
        self.assertIsNone(safe_candidate(row | {"route_risks": ["known divergence"]}))

    def test_declared_protocol_constraints(self):
        config = read(HERE / "config.json")
        validate_config(config)
        p = schedule({"source": "native", "id": "fixture"}, config)["profiles"]
        self.assertEqual(p[:2], [["low", "Q1", 48], ["standard", "C", 128]])
        with self.assertRaisesRegex(ValueError, "Replay"):
            validate_config(config | {"profiles": {"standard": 127}})


@unittest.skipUnless(os.environ.get("STS2_LS2A_PILOT"), "Set STS2_LS2A_PILOT to the parent of pilot runs")
class NativeEvidence(unittest.TestCase):
    def test_serial_parallel_semantic_equality_and_coverage(self):
        before = Path(os.environ["STS2_LS2A_PILOT"])
        runs = []
        for mode in ("serial", "parallel"):
            directory = before / f"ls2a-qualified-{mode}"
            native = read(directory / "catalog.json")
            config = read(HERE / "pilot.json")
            generated = synthetic(native, config, 20, config["namespace"])
            self.assertEqual(len({case["recipe"] for case in generated}), 20)
            self.assertEqual({c["spec"]["character"] for c in generated}, {c["name"] for c in native["characters"]})
            self.assertEqual({c["spec"]["act"] for c in generated}, {1, 2, 3})
            self.assertEqual({c["room"] for c in generated}, {"Monster", "Elite", "Boss"})
            with closing(store.open_store(directory / "search.sqlite")) as db:
                results = dict(store.results(db, "main"))
                self.assertEqual(len(results), 20)
                self.assertTrue(all(r["outcome"] == "complete" for r in results.values()))
                runs.append({key: (r["exact"], [semantic_cell(c) for c in r["cells"]])
                             for key, r in results.items()})
        self.assertEqual(*runs)


if __name__ == "__main__":
    unittest.main()
