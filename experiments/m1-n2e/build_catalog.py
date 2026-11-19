"""Map native static variables and localized rules onto ordered mechanism nodes."""
import json

from extract import HERE, IDS

QUALIFIED_GAME_SHA256 = "62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3"



def damage(v, target="selected_enemy"):
    return dict(kind="Damage", target=target, amount=v["Damage"], hits=v.get("HitCount", 1),
                modifiers=["strength_per_hit"])


def block(v):
    return dict(kind="Block", target="self", amount=v["Block"], modifiers=["dexterity"])


def draw(count):
    return dict(kind="Draw", target="self", count=count, source_zone="draw_pile")


def generate(v):
    return dict(kind="GenerateCard", target="self", card_family="shiv", count=v["Cards"],
                destination_zone="hand")


def power(name, amount, target="self", **details):
    return dict(kind="GainPower" if target == "self" else "ApplyPower",
                power=name, amount=amount, target=target, **details)


def trigger(event, effect, duration):
    return dict(kind="TriggeredEffect", event=event, duration=duration, effects=[effect])


def unknown(reason):
    return dict(kind="UnsupportedEffect", reason=reason)


def effects(card, v):
    match card:
        case "STRIKE_IRONCLAD" | "STRIKE_SILENT" | "TWIN_STRIKE" | "SLICE" | "SHIV":
            return [damage(v)]
        case "DEFEND_IRONCLAD" | "DEFEND_SILENT":
            return [block(v)]
        case "BASH":
            return [damage(v), power("vulnerable", v["VulnerablePower"], "selected_enemy",
                                     duration="power_stacks")]
        case "INFLAME":
            return [power("strength", v["StrengthPower"], duration="combat")]
        case "POMMEL_STRIKE":
            return [damage(v), draw(v["Cards"])]
        case "SHRUG_IT_OFF" | "BACKFLIP":
            return [block(v), draw(v["Cards"])]
        case "FLAME_BARRIER":
            return [block(v), trigger("when_attacked",
                    dict(kind="Damage", target="attacker", amount=v["DamageBack"], hits=1),
                    "current_turn"), unknown("retaliation_hook_details")]
        case "IRON_WAVE":
            return [block(v), damage(v)]
        case "SURVIVOR":
            return [block(v), dict(kind="Discard", target="self", count=1, source_zone="hand",
                                   selection="player_choice"), unknown("choice_edge_cases")]
        case "BLADE_DANCE":
            return [generate(v)]
        case "ACCURACY":
            return [power("accuracy", v["AccuracyPower"], duration="combat", card_family="shiv")]
        case "FOOTWORK":
            return [power("dexterity", v["DexterityPower"], duration="combat")]
        case "DODGE_AND_ROLL":
            return [block(v), trigger("next_turn", block(v), "once"),
                    unknown("delayed_block_snapshot_and_hook_details")]
        case "CLOAK_AND_DAGGER":
            return [block(v), generate(v)]
        case "PREDATOR":
            return [damage(v), trigger("next_turn", draw(2), "once"),
                    unknown("lethal_terminal_continuation_mismatch")]
        case "LEG_SWEEP":
            return [power("weak", v["WeakPower"], "selected_enemy", duration="power_stacks"), block(v)]
        case _:
            raise ValueError(card)


def build_catalog(native):
    if native["game_dll_sha256"] != QUALIFIED_GAME_SHA256:
        raise ValueError("The semantic mapping needs review for this game DLL")
    characters = {card: character for character, ids in IDS.items() for card in ids.split()}
    specs = []
    for row in native["cards"]:
        card = row["id"]
        variants = []
        for source in row["variants"]:
            variant = {key: value for key, value in source.items() if key != "variables"}
            nodes = effects(card, source["variables"])
            if "Exhaust" in source["keywords"]:
                nodes.append(dict(kind="Exhaust", target="played_card", event="on_play_cleanup"))
            variants.append({**variant, "effects": nodes})
        partial = any(node["kind"] == "UnsupportedEffect" for v in variants for node in v["effects"])
        specs.append({"id": card, "character": characters[card],
                      "card_family": "shiv" if card == "SHIV" else None,
                      "qualification": "static_partial" if partial else "static_described",
                      "sources": {"native": "static-evidence.json", "rule_text": card + ".description"},
                      "variants": variants})
    return {**native, "cards": specs}


if __name__ == "__main__":
    native = json.loads((HERE / "static-evidence.json").read_text(encoding="utf-8"))
    (HERE / "cards.json").write_text(json.dumps(build_catalog(native), indent=2, sort_keys=True) + "\n",
                                    encoding="utf-8")
