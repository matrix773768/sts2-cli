"""Versioned card mechanics for public observations and unordered deck multisets."""
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

SCHEMA = "sts2.card-semantics.v1"
DECK_SOURCES = frozenset({"offline_root", "visible_deck", "public_history"})
PREVIEW_FIELDS = ("damage_per_hit", "hits", "block", "draw")


def serialize(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(serialize(value).encode("utf-8")).hexdigest()


def load_catalog():
    data = json.loads(Path(__file__).with_name("cards.json").read_text(encoding="utf-8"))
    return Catalog(data["game_dll_sha256"], data["cards"])


@dataclass(frozen=True, slots=True)
class CardInstance:
    spec_ref: str
    upgrade_level: int = 0
    permanent_modifiers: tuple[tuple[str, str, int], ...] = ()
    public_modifiers: tuple[tuple[str, str, int], ...] = ()
    occurrence_id: int | None = None

    def __post_init__(self):
        if not isinstance(self.spec_ref, str) or not self.spec_ref or type(self.upgrade_level) is not int or self.upgrade_level < 0:
            raise ValueError("Expected a card ID and nonnegative upgrade level")
        for item in (*self.permanent_modifiers, *self.public_modifiers):
            kind, identifier, amount = item
            if not isinstance(kind, str) or not kind or not isinstance(identifier, str) or not identifier:
                raise ValueError("Expected a public modifier kind and rule ID")
            if type(amount) is not int:
                raise ValueError("Expected an integral public modifier amount")


@dataclass(frozen=True, slots=True)
class DeckSpec:
    character: str
    cards: tuple[CardInstance, ...]
    source: str
    complete: bool

    def __post_init__(self):
        if self.source not in DECK_SOURCES or type(self.complete) is not bool or not self.character:
            raise ValueError("Expected character, deck provenance and completeness")


class Catalog:
    def __init__(self, rule_version, specs):
        self.rule_version = rule_version
        self._specs = {spec["id"]: serialize(spec) for spec in specs}
        if len(self._specs) != len(specs):
            raise ValueError("Duplicate card rule ID")
        self.content_sha256 = digest([json.loads(self._specs[key]) for key in sorted(self._specs)])

    def encode_card_spec(self, card_id):
        spec = json.loads(self._specs[card_id]) if card_id in self._specs else {
            "id": card_id, "character": None, "qualification": "unknown", "card_family": None, "variants": [],
        }
        return {"schema": SCHEMA, "rule_version": self.rule_version, **spec}

    def encode_card_instance(self, instance, mode="mechanics"):
        identity = mode == "identity"
        if not identity and mode != "mechanics":
            raise ValueError("Expected identity or mechanics")
        result = {
            "upgrade_level": instance.upgrade_level,
            "permanent_modifiers": _modifiers(instance.permanent_modifiers),
            "public_modifiers": _modifiers(instance.public_modifiers),
        }
        if identity:
            return {"spec_ref": instance.spec_ref, **result}
        spec = self.encode_card_spec(instance.spec_ref)
        variant = next((v for v in spec["variants"] if v["level"] == instance.upgrade_level), None)
        if variant is None:
            variant = {"cost": None, "x_cost": None, "type": None, "rarity": None,
                       "targeting": None, "keywords": None,
                       "effects": [{"kind": "UnsupportedEffect", "reason": "unqualified_variant"}]}
        else:
            variant = {k: v for k, v in variant.items() if k != "level"}
        return {**result, **variant, "character": spec["character"], "card_family": spec["card_family"],
                "qualification": "unknown" if variant["cost"] is None else spec["qualification"]}

    def encode_deck(self, deck, mode="mechanics"):
        if any(card.public_modifiers for card in deck.cards):
            raise ValueError("Deck requires permanent modifiers only")
        payload = self._envelope(mode)
        counts = Counter(serialize(self.encode_card_instance(card, mode)) for card in deck.cards)
        payload.update(character=deck.character, complete=deck.complete,
                       cards=[{"card": json.loads(card), "count": counts[card]} for card in sorted(counts)])
        identity = Counter(serialize(self.encode_card_instance(card, "identity")) for card in deck.cards)
        return {**payload, "content_sha256": digest([self.rule_version, self.content_sha256,
                                                      deck.character, deck.complete, sorted(identity.items())]),
                "source": deck.source}

    def decode_identity_deck(self, payload):
        """Rebuild the unordered deck and verify the schema version and content digest."""
        if payload["mode"] != "identity":
            raise ValueError("Decoding requires the identity deck")
        cards = []
        for group in payload["cards"]:
            card = group["card"]
            count = group["count"]
            if type(count) is not int or count < 1:
                raise ValueError("Expected a positive integer count")
            modifiers = tuple((m["kind"], m["id"], m["amount"]) for m in card["permanent_modifiers"])
            instance = CardInstance(card["spec_ref"], card["upgrade_level"], modifiers)
            cards.extend([instance] * count)
        deck = DeckSpec(payload["character"], tuple(cards), payload["source"], payload["complete"])
        if self.encode_deck(deck, "identity") != payload:
            raise ValueError("Deck payload is noncanonical or incompatible with this catalog")
        return deck

    def encode_card_context(self, observation, mode="mechanics"):
        # A binding is local to one active menu. Candidate indices use a separate namespace.
        hand = {c.index: c for c in observation.hand}
        bindings = []
        actions = []
        targets = {}
        for action in observation.actions:
            if action.card is not None and action.target is not None:
                targets.setdefault(action.card, set()).add(action.target)
        for action in observation.actions:
            choice = action.choice
            bindings.append({"action_index": action.index, "hand_index": action.card,
                             "target_index": action.target,
                             "choice_index": choice.index if choice is not None else None})
            if action.card is None:
                actions.append({"kind": "end_turn"})
                continue
            card = hand[action.card]
            preview = {key: getattr(action.preview, key, None) for key in PREVIEW_FIELDS}
            actions.append({
                "kind": "play_card",
                "card": self.encode_card_instance(CardInstance(card.id, card.upgrade), mode),
                "choice": self.encode_card_instance(CardInstance(choice.id, choice.upgrade), mode)
                if choice is not None else None,
                "current_public_cost": action.cost,
                "valid_targets": sorted(targets.get(card.index, ())),
                "target": next(({"hp": enemy.hp, "block": enemy.block,
                                 "attack_hits": list(enemy.attack_hits), "powers": _powers(enemy.powers)}
                                for enemy in observation.enemies if enemy.index == action.target), None),
                "preview": preview,
                "preview_qualification": "allowlisted_fields" if any(v is not None for v in preview.values())
                else "unavailable",
                "missing_fields": [key for key, value in preview.items() if value is None]
                + (["current_public_cost"] if action.cost is None else [])
                + ["instance_modifiers"],
            })
        features = {**self._envelope(mode), "preview_source": "n2a1_public_allowlist",
                    "turn": observation.turn, "hp": observation.hp, "block": observation.block,
                    "energy": observation.energy, "draw_count": observation.draw_count,
                    "powers": _powers(observation.powers), "actions": actions,
                    "hand": [self.encode_card_instance(CardInstance(c.id, c.upgrade), mode)
                             for c in observation.hand]}
        return features, bindings

    def _envelope(self, mode):
        if mode not in ("identity", "mechanics"):
            raise ValueError("Expected identity or mechanics")
        return {"schema": SCHEMA, "rule_version": self.rule_version,
                "catalog_sha256": self.content_sha256, "mode": mode}


def _modifiers(items):
    return [{"kind": kind, "id": identifier, "amount": amount}
            for kind, identifier, amount in sorted(items)]


def _powers(items):
    return [{"id": power.id, "amount": power.amount} for power in sorted(items, key=lambda p: p.id)]


def deck_from_root(character, cards):
    """Adapt N2A.2 card rows only. Root metadata never enters the contract."""
    return DeckSpec(character, tuple(CardInstance(row["id"], row["upgrade"]) for row in cards),
                    "offline_root", True)
