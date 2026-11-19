"""Public-only composition and bounded edits. All numeric preferences have native semantics."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-ls2a"))
from space import digest

VERSION = "ls2b.spec.v1"
GENERATOR = "composition.v1"
PARAMS = ("damage", "block", "power", "draw", "unscored")


def context(public):
    counts = Counter()
    metadata = public["native_card_metadata"]
    n = sum(e["count"] for e in public["identity_deck"]["cards"])
    for entry in public["identity_deck"]["cards"]:
        card = metadata.get(entry["card"]["spec_ref"])
        if card:
            counts[card["type"]] += entry["count"]
            if "Block" in card["variables"]:
                counts["block_cards"] += entry["count"]
    for entry in public["mechanics_deck"]["cards"]:
        kinds = {effect["kind"] for effect in entry["card"]["effects"]}
        for kind in kinds:
            counts[kind] += entry["count"]
    enemies = public["enemies"]
    player = public["player"]
    return dict(hp=player["hp"]/max(1, player["max_hp"]), enemies=len(enemies),
                pressure=sum(i.get("total_damage", i.get("damage", 0)) or 0 for e in enemies
                             for i in e["intents"])/max(1, player["hp"]),
                attack=counts["Attack"]/n, block=counts["block_cards"]/n,
                setup=(counts["Power"]+counts["ApplyPower"]+counts["GenerateCard"])/n,
                draw=counts["Draw"]/n, missing=counts["UnsupportedEffect"]/n)


def weights(damage, block, power, draw, unscored):
    return dict(zip(PARAMS, (damage, block, power, draw, unscored)))


def canonical(spec):
    spec = deepcopy(spec)
    if spec["setup_turns"] == 0 or spec["opening"] == spec["finish"]:
        spec.update(opening=spec["finish"].copy(), setup_turns=0, finish_pct=50)
    return spec


def generate(ctx):
    opening = weights(3, 4, min(60, 21+int(54*ctx["setup"])),
                      min(40, 9+int(25*ctx["draw"])), 4+int(10*ctx["missing"]))
    finish = weights(6+int(4*ctx["attack"]), 3+int(5*ctx["block"]), 6, 5, 3)
    reserve = min(65, int(15+30*(1-ctx["hp"])+15*min(1, ctx["pressure"])))
    turns = min(4, 1+int(5*ctx["setup"]))
    hp_gate = 40+int(25*ctx["hp"])
    targets = ("weakest", "threat", "largest") if ctx["enemies"] > 1 else ("weakest",)
    # Explicitly enumerate a small product, interleaving objectives before target variants.
    proposals = []
    for target in targets:
        for length in (turns, 0, min(5, turns+2)):
            for margin in (reserve, min(80, reserve+25)):
                proposals.append(canonical(dict(version=VERSION, objective="surviving_victory",
                    potion_policy="preserve", opening=opening, finish=finish, setup_turns=length,
                    finish_pct=hp_gate, reserve_pct=margin, target=target)))
    # Different goals before minor variations in HP reserve.
    order = proposals[::2] + proposals[1::2]
    return order


def feedback(result):
    status = result["status"]
    flags = []
    trace = result.get("trace", [])
    if status in ("death", "action_cap", "transition_cap") and trace:
        last = trace[-1]
        if result["remaining"] * 2 >= result["initial_enemy_hp"]:
            flags.append("insufficient_output")
        if last["incoming"] - last["block"] >= last["hp"] or last["energy"] == 0:
            flags.append("resource_pressure")
    return dict(observed=status, detail=result.get("detail"), gaps=result.get("gaps", []),
                heuristic=flags, scope="one_budgeted_prediction")


def edits(spec, fb, ctx):
    if fb["observed"] not in ("death", "action_cap", "transition_cap"):
        return []
    ops = ["raise_reserve", "accelerate_finish", "retarget"]
    if "insufficient_output" in fb["heuristic"]:
        ops = ["accelerate_finish", "retarget", "raise_reserve"]
    if "resource_pressure" in fb["heuristic"]:
        ops.insert(0, ops.pop(ops.index("raise_reserve")))
    changed = []
    for op in ops:
        child = deepcopy(spec)
        if op == "raise_reserve":
            child["reserve_pct"] = min(80, child["reserve_pct"]+24)
            for phase in ("opening", "finish"):
                child[phase]["block"] = min(12, child[phase]["block"]+3)
        elif op == "accelerate_finish":
            child["setup_turns"] = max(0, child["setup_turns"]-1)
            child["finish"]["damage"] = min(12, child["finish"]["damage"]+3)
            child["finish_pct"] = min(90, child["finish_pct"]+20)
        elif ctx["enemies"] > 1:
            child["target"] = "weakest" if child["target"] == "threat" else "threat"
        else:
            continue
        changed.append((op, canonical(child)))
    return changed
