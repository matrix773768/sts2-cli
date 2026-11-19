"""Checks for public-only ranking, integrity and the optional real-engine seam."""
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
from time import monotonic
import unittest

from ls1_design import HERE, PROTOCOL, STRATEGIES, manifest, read, verify_groups
from loop import cell, examples, load_model, validate_experiment_rows
from search import bank, request, restore, search, semantic, setup
import model


def public_fixture():
    hand = dict(id="CARD.INFLAME", type="Power", cost=1, can_play=True, target_type="Self")
    return dict(decision="combat_play", context={"act": 2}, round=1, energy=3, max_energy=3, hand=[hand],
                draw_pile_count=2, discard_pile_count=0, enemies=[
                    dict(name="fixture", hp=60, max_hp=60, block=3, intents=[dict(type="Attack", damage=9)])
                ], player=dict(name="IRONCLAD.title", hp=40, max_hp=80, block=0, gold=99,
                               potions=[], relics=[], deck=[
                                   {"id": "CARD.INFLAME", "upgraded": False}, {"id": "CARD.TWIN_STRIKE", "upgraded": True}
                               ]))


class ContractTests(unittest.TestCase):
    def test_hidden_data_does_not_enter_either_representation(self):
        obs = public_fixture()
        visible = dict(potions=[None, None, None], relics=[])
        wanted, gaps = model.public_input(obs, visible)
        self.assertFalse(gaps)
        for mapping in (obs, obs["player"], obs["hand"][0], obs["enemies"][0], obs["player"]["deck"][0], visible):
            mapping.update(rng="bad", live="bad", draw_order=["bad"], future="bad", root_stamp="bad")
        state, gaps = model.public_input(obs, visible)
        self.assertEqual(wanted, state)
        self.assertFalse(gaps)
        clean = json.dumps(state)
        self.assertNotIn("bad", clean)
        swapped = deepcopy(obs)
        swapped["player"]["deck"].reverse()
        self.assertEqual(wanted, model.public_input(swapped, visible)[0])

    def test_no_cross_split_recipe_family_history_seed_pair_or_root(self):
        items = manifest()
        actual = {c["split"] for c in items}
        self.assertEqual(actual, {"train", "selection", "report", "reachable", "feedback", "pilot"})
        train = next(c for c in items if c["split"] == "train")
        report = next(c for c in items if c["split"] == "report")
        for field in ("recipe", "family", "history", "seed", "pair", "root_stamp"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                verify_groups([train | {field: "overlap"}, report | {field: "overlap"}])

    def test_order_fallbacks(self):
        visible = dict(potions=[None]*3, relics=[])
        state, gaps = model.public_input(public_fixture(), visible)
        versions = {k: "version" for k in model.MODEL_VERSIONS}
        compatible = {"encoder": model.ENCODER, "versions": versions, "models": {}}
        for bundle, expected in (
            (None, "model_missing"),
            (compatible | {"encoder": "foreign"}, "model_version_mismatch"),
            (compatible, "model_error"),
        ):
            order, reason, elapsed = model.order(state, gaps, "learned_search", 48, bundle, versions)
            self.assertEqual((order, reason), (STRATEGIES, expected))
            self.assertGreaterEqual(elapsed, 0)
        obs = public_fixture()
        obs["player"]["deck"][0]["id"] = "CARD.UNKNOWN"
        state, gaps = model.public_input(obs, visible)
        self.assertEqual(model.order(state, gaps, "learned_search", 48, compatible, versions)[:2],
                         (STRATEGIES, "unsupported_public_mechanism:card_mechanism"))


@unittest.skipUnless((HERE / "evidence/ledger.json.gz").exists(), "Frozen experiment evidence pending")
class EvidenceTests(unittest.TestCase):
    def test_experience_versions_budget_and_feedback(self):
        folder = HERE / "evidence"
        contract = read(folder / "contract.json")
        with gzip.open(folder / "ledger.json.gz", "rt", encoding="utf-8") as stream:
            ledger = json.load(stream)
        subset = [r for group in ledger.values() for r in group]
        validate_experiment_rows(subset, contract["manifest"], contract["versions"])
        for row in subset:
            for exp in row["experience"]:
                r = exp["outcome"]
                attempted = r["attempts"]
                self.assertLessEqual(r["transitions"], r["cap"])
                self.assertEqual(r["transitions"], sum(a["transitions"] for a in attempted)
                                 + r["quality_transitions"] + r["verification_transitions"])
                self.assertEqual(r["executed_initial"], r["planned"][:len(r["executed_initial"])])
                self.assertGreaterEqual(r["search_ms"], r["ordering_ms"])
                self.assertGreaterEqual(r["ordering_ms"], r["model_ms"])
                if r["status"] == "qualified_win":
                    self.assertTrue(attempted[-1]["verified_win"])
                    self.assertEqual(r["first_path_size"], r["verification_transitions"])
                    self.assertGreaterEqual(r["locked"]["hp"], r["first_locked"]["hp"])
                    self.assertEqual(r["first_locked"]["potions"], r["locked"]["potions"])
        self.assertTrue(any(e["outcome"]["executed_order_changed"] for row in ledger["report"]
                            for e in row["experience"] if e["audit"]["mode"] == "learned_search"))
        self.assertEqual(list(examples(ledger["report"], "train")), [])
        first = load_model(folder / "model-v1.json", strict=True)
        second = load_model(folder / "model-v2.json", strict=True)
        self.assertEqual(first["sha256"], second["provenance"]["parent"])
        self.assertGreater(second["provenance"]["train_rows"], first["provenance"]["train_rows"])


@unittest.skipUnless(os.environ.get("STS2_LS1_NATIVE_OUT"), "Set STS2_LS1_NATIVE_OUT for native checks")
class NativeTests(unittest.TestCase):
    def test_exact_permutation_safe_fallback_and_cold_repeat(self):
        output = Path(os.environ["STS2_LS1_NATIVE_OUT"]).resolve()
        output.mkdir(parents=True, exist_ok=False)
        versions = setup(output)
        pilot = {c["id"]: c for c in manifest() if c["split"] == "pilot"}
        pinned = next(r for r in read(HERE / "baseline.json")["rows"]
                      if r["result"]["cap"] == 128 and r["result"]["status"] == "qualified_win")
        case = pilot[pinned["id"]]

        def candidate(game, public, identity, bundle):
            state, gaps = model.public_input(public, identity["resources"])
            result = cell(game, case, state, gaps, versions, bundle,
                          ("learned_search", 64, 128, None), 0.0)
            return result, semantic(result["outcome"] | {"root_stamp": result["audit"]["root_stamp"]})

        with restore(output, case, versions, monotonic()+100) as (game, public, identity):
            expected = pinned["result"]
            self.assertEqual(expected, semantic(search(game, 64, 128)))
            self.assertEqual(expected, semantic(search(game, 64, 128, order=STRATEGIES)))
            alternate = search(game, 64, 128, order=STRATEGIES[::-1])
            self.assertEqual(alternate["executed_initial"][0], STRATEGIES[-1])
            for bundle, reason in ((None, "model_missing"),
                                   ({"sha256": None, "encoder": "wrong"}, "model_version_mismatch"),
                                   ({"sha256": None, "encoder": model.ENCODER, "versions": model.model_versions(versions),
                                     "models": {"mechanics": {"parameters": [{}]}}}, "model_error")):
                result, details = candidate(game, public, identity, bundle)
                self.assertEqual(result["audit"]["fallback"], reason)
                self.assertEqual(expected, details)
            with self.assertRaisesRegex(bank.f1.i2.StopRun, "exact permutation"):
                request(game, "i1_f3b", 64, ls1_order=["Q1"] * 4)
            self.assertEqual(expected, semantic(search(game, 64, 128)))
        other = next(c for c in pilot.values() if c != case)
        with restore(output, other, versions, monotonic()+50) as (game, _, _):
            self.assertNotEqual(expected["root_stamp"], search(game, 64, 128)["root_stamp"])
        with restore(output, case, versions, monotonic()+50) as (game, _, _):
            self.assertEqual(expected, semantic(search(game, 64, 128)))


if __name__ == "__main__":
    unittest.main()
