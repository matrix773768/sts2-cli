import json
from pathlib import Path
import sys

import unittest

from build_catalog import build_catalog
from semantics import CardInstance, Catalog, DeckSpec, digest, load_catalog, serialize

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-n2a1"))
from interaction import Observation


def instance(card, upgrade=0, **kwargs):
    return CardInstance(card, upgrade, **kwargs)


def deck(*cards):
    return DeckSpec("Ironclad", cards, "visible_deck", True)


class SemanticsTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()

    def test_sources_and_versions(self):
        catalog = self.catalog
        evidence = json.loads((HERE / "static-evidence.json").read_text())
        stored = json.loads((HERE / "cards.json").read_text())
        assert build_catalog(evidence) == stored
        with self.assertRaises(ValueError):
            build_catalog({**evidence, "game_dll_sha256": "different_version"})
        assert len(stored["cards"]) == 22
        reversed_catalog = Catalog(stored["game_dll_sha256"], list(reversed(stored["cards"])))
        assert reversed_catalog.content_sha256 == catalog.content_sha256
        assert catalog.encode_card_spec("BASH") == reversed_catalog.encode_card_spec("BASH")
        assert digest(catalog.encode_card_spec("BASH")) != digest(
            Catalog("different_version", stored["cards"]).encode_card_spec("BASH"))
        stored["cards"][0]["variants"][0]["cost"] += 1
        changed = Catalog(stored["game_dll_sha256"], stored["cards"])
        assert changed.content_sha256 != catalog.content_sha256


    def test_mechanisms_and_upgrades(self):
        catalog = self.catalog
        def encode(card, level=0):
            return catalog.encode_card_instance(instance(card, level))
        strike, twin = encode("STRIKE_IRONCLAD"), encode("TWIN_STRIKE")
        assert strike["effects"][0]["kind"] == twin["effects"][0]["kind"] == "Damage"
        assert twin["effects"][0]["hits"] == 2
        assert "strength_per_hit" in twin["effects"][0]["modifiers"]
        assert encode("INFLAME")["effects"][0]["power"] == "strength"
        assert encode("BLADE_DANCE")["effects"][0]["card_family"] == encode("SHIV")["card_family"]
        assert encode("ACCURACY")["effects"][0]["card_family"] == encode("SHIV")["card_family"]
        assert encode("POMMEL_STRIKE")["cost"] == 1
        assert encode("POMMEL_STRIKE", 1)["effects"][1]["count"] == 2
        assert encode("PREDATOR")["effects"][1]["effects"][0]["kind"] == "Draw"
        assert [node["kind"] for node in encode("IRON_WAVE")["effects"]] == ["Block", "Damage"]
        assert encode("PREDATOR")["qualification"] == "static_partial"
        for card in (encode("UNKNOWN"), encode("BASH", 100)):
            assert card["cost"] is None
            assert card["effects"][0]["kind"] == "UnsupportedEffect"


    def test_deck_multiset_and_roundtrip(self):
        catalog = self.catalog
        strike = instance("STRIKE_IRONCLAD", occurrence_id=22)
        copy = instance("STRIKE_IRONCLAD", occurrence_id=23)
        upgraded = instance("STRIKE_IRONCLAD", 1)
        modified = instance("STRIKE_IRONCLAD", permanent_modifiers=(("enchantment", "SHARP", 2),))
        encoded = catalog.encode_deck(deck(strike, modified, copy, upgraded))
        assert encoded == catalog.encode_deck(deck(upgraded, strike, copy, modified))
        assert sorted(row["count"] for row in encoded["cards"]) == [1, 1, 2]
        assert encoded == json.loads(serialize(encoded))
        identity = catalog.encode_deck(deck(strike, modified, copy, upgraded), "identity")
        decoded = catalog.decode_identity_deck(json.loads(serialize(identity)))
        assert catalog.encode_deck(decoded) == encoded
        with self.assertRaises(ValueError):
            catalog.decode_identity_deck({**identity, "content_sha256": "bad"})
        assert catalog.encode_deck(deck(strike, copy)) != catalog.encode_deck(deck(strike, upgraded))
        assert catalog.encode_deck(deck(strike))["content_sha256"] == catalog.encode_deck(
            deck(strike), "identity")["content_sha256"]
        assert "occurrence_id" not in serialize(encoded)
        assert "STRIKE_IRONCLAD" not in serialize(encoded)
        assert catalog.encode_card_instance(strike, "identity")["spec_ref"] == "STRIKE_IRONCLAD"
        assert "effects" not in catalog.encode_card_instance(strike, "identity")
        with self.assertRaises(ValueError):
            catalog.encode_deck(deck(instance("BASH", public_modifiers=(("temporary", "COST", 0),))))


    def test_public_context_and_choice_bindings(self):
        catalog = self.catalog
        def card(index, id, upgrade=0):
            return dict(index=index, id=id, upgrade=upgrade)
        wire = dict(turn=2, hp=10, block=0, energy=2, draw_count=4,
                    hand=[card(0, "SURVIVOR"), card(1, "BACKFLIP"), card(2, "BACKFLIP", 1)],
                    enemies=[], powers=[dict(id="DEXTERITY_POWER", amount=3)],
                    actions=[dict(index=0),
                             dict(index=1, card=0, cost=0, choice=card(0, "BACKFLIP"), preview=dict(block=11)),
                             dict(index=2, card=0, cost=0, choice=card(1, "BACKFLIP", 1)),
                             dict(index=3, card=1, cost=1)],
                    hidden_rng="PRIVATE", private_preview={"draw": 90}, draw_order=["SECRET"])
        features, bindings = catalog.encode_card_context(Observation.decode(wire))
        assert features["powers"][0]["amount"] == 3
        assert features["actions"][1]["current_public_cost"] == 0
        assert features["actions"][1]["preview"]["block"] == 11
        assert features["actions"][1]["choice"] != features["actions"][2]["choice"]
        assert bindings[1]["choice_index"] == 0 and bindings[2]["choice_index"] == 1
        assert features["actions"][3]["preview"]["draw"] is None
        assert "draw" in features["actions"][3]["missing_fields"]
        assert features["hand"][1] == catalog.encode_card_instance(instance("BACKFLIP"))
        assert all(secret not in serialize(features) for secret in ("PRIVATE", "SECRET", "private_preview"))
        assert json.loads(serialize(features)) == features


    def test_unqualified_cards_and_exact_duplicate_choices(self):
        from interaction import Action
        from environment import Card
        hand = tuple(Card(i, card, 0) for i, card in enumerate(
            ("SURVIVOR", "IRON_WAVE", "BACKFLIP", "PREDATOR", "BACKFLIP")))
        obs = Observation(1, 10, 0, 3, 4, hand, (), (
            Action(0, 0, cost=1, choice=Card(1, "BACKFLIP", 0)),
            Action(1, 0, cost=1, choice=Card(3, "BACKFLIP", 0)),
            Action(2, 1, cost=1), Action(3, 2, cost=1), Action(4, 3, cost=2)))
        features, bindings = self.catalog.encode_card_context(obs)
        a, b, *unqualified = features["actions"]
        assert a["choice"] == b["choice"]
        assert bindings[0]["choice_index"] != bindings[1]["choice_index"]
        for action in unqualified:
            assert action["preview_qualification"] == "unavailable"
            assert set(action["preview"].values()) == {None}
            assert action["card"]["effects"]

    def test_target_specific_previews(self):
        catalog = self.catalog
        from interaction import Action, Enemy, Power, Preview
        from environment import Card
        obs = Observation(3, 10, 0, 2, 4, (Card(0, "TWIN_STRIKE", 0),),
                          (Enemy(3, 5, 0, (7,)), Enemy(7, 12, 2, (8,), (), (Power("VULNERABLE_POWER", 1),))),
                          (Action(0, 0, 3, 1, preview=Preview(5, 2)),
                           Action(1, 0, 7, 1, preview=Preview(7, 2))))
        features, bindings = catalog.encode_card_context(obs)
        a, b = features["actions"]
        assert a["valid_targets"] == b["valid_targets"] == [3, 7]
        assert a["preview"]["damage_per_hit"] == 5 and b["preview"]["damage_per_hit"] == 7
        assert b["target"]["powers"][0]["amount"] == 1 and bindings[1]["target_index"] == 7


    def test_schema_and_example(self):
        catalog = self.catalog
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is unavailable")
        schema = json.loads((HERE / "schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        example = json.loads((HERE / "example.json").read_text())
        for name in ("card_spec", "identity_deck", "mechanics_deck", "context"):
            jsonschema.validate(example[name], schema)
        for binding in example["bindings"]:
            jsonschema.validate(binding, schema)
        for card_id in catalog._specs:
            jsonschema.validate(catalog.encode_card_spec(card_id), schema)
