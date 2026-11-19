"""Native observation-only target experiment for the four S3B Flame Barrier roots."""
import argparse
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
from pathlib import Path
from time import perf_counter

from benchmark_n1 import BASELINE, ROOT, bank, inputs, s3a
from summarize import read


@dataclass(frozen=True)
class Enemy:
    index: int
    hp: int
    block: int
    incoming: int


@dataclass(frozen=True)
class Move:
    card: int
    target: int | None
    damage: int
    block: int
    draw: int
    cost: int
    power: bool


@dataclass(frozen=True)
class Observation:
    block: int
    enemies: tuple[Enemy, ...]
    moves: tuple[Move, ...]


def observe(state):
    enemies = tuple(Enemy(e["index"], e["hp"], e["block"],
                          sum(i.get("damage", 0) * i.get("hits", 1) for i in e["intents"] or []))
                    for e in state["enemies"] if e["hp"] > 0)
    moves = []
    for card in state["hand"]:
        if not card["can_play"] or card["cost"] < 0:
            continue
        stats = card["stats"] or {}
        target_type = card["target_type"]
        if target_type == "AnyEnemy":
            candidates = [(x["target_index"], x.get("total_damage", x["damage"]))
                          for x in card.get("damage_by_target", []) if "damage" in x]
        elif target_type in ("None", "Self", "AllEnemies", "RandomEnemy", "TargetedNoCreature"):
            damage = max(stats.get("damage", 0), stats.get("calculateddamage", 0))
            candidates = [(None, damage * max(1, stats.get("repeat", 1)))]
        else:
            continue
        for target, damage in candidates:
            moves.append(Move(card["index"], target, damage,
                              stats.get("block", 0), stats.get("cards", 0), card["cost"],
                              card["type"] == "Power"))
    return Observation(state["player"]["block"], enemies, tuple(moves))


def decide(view, policy):
    enemies = {enemy.index: enemy for enemy in view.enemies}
    incoming = max(0, sum(e.incoming for e in view.enemies) - view.block)

    def score(move):
        enemy = enemies.get(move.target)
        damage = move.damage if enemy is None else min(enemy.hp, max(0, move.damage - enemy.block))
        kill = 30 + 5 * enemy.incoming if enemy is not None and damage >= enemy.hp else 0
        return (3 * damage + 5 * min(incoming, move.block) + kill + 4 * move.draw
                + 5 * move.power - 2 * move.cost + (move.cost == 0))

    selected = max(view.moves, key=score, default=None)
    if selected is None or score(selected) <= 0:
        return dict(action="end_turn")
    if policy == "PUBLIC_THREAT_V1" and selected.target is not None and selected.damage > 0:
        enemy = enemies[selected.target]
        if selected.damage < enemy.hp + enemy.block:
            viable = [m for m in view.moves if m.card == selected.card and m.target in enemies
                      and m.damage > enemies[m.target].block]
            if viable:
                selected = max(viable, key=lambda m: (enemies[m.target].incoming, score(m)))
    args = dict(card_index=selected.card)
    if selected.target is not None:
        args["target_index"] = selected.target
    return dict(action="play_card", args=args)


def rollout(game, state, policy):
    actions = []
    started = perf_counter()
    while state["decision"] == "combat_play" and len(actions) < 48:
        action = decide(observe(state), policy)
        actions.append(dict(round=state["round"], hp=state["player"]["hp"],
                            enemies=state["enemies"], action=action))
        state = game.execute_action(action)
    hot_ms = 1000 * (perf_counter() - started)
    final = game.request("f1_final")
    detail = state["decision"]
    status = bank.f1.outcome({"native_final": final}, state)
    if status == "win":
        status = "native_win"
    elif detail == "combat_play":
        status = "truncated"
    return dict(policy=policy, status=status, detail=detail, actions=actions, final=final, hot_ms=hot_ms)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = read(args.baseline)
    completed = {(r["case"]["id"], r["result"]["strategy"]) for r in rows}
    cases = list(inputs())
    if completed != {(c["case"]["id"], policy) for c in cases for policy in BASELINE}:
        raise ValueError("Complete the baseline first")
    output = args.output.resolve()
    output.mkdir(parents=True)
    versions = s3a.solver_binding(output, s3a.FIXED, ROOT / "logs/m1-e3f/release")
    b1b = s3a.b1b
    results = []
    for item in cases:
        case = item["case"]
        if case.get("template") != "special_defense" or case["spec"]["encounter"] != "BOWLBUGS_NORMAL":
            continue
        for policy in ("PUBLIC_SCORE_V1", "PUBLIC_THREAT_V1"):
            with ExitStack() as stack:
                game, _ = s3a.attested(output, stack, versions)
                surfaces, _ = b1b.synth.capture(game, case["spec"])
                b1b.equal("native root", item["root_sha256"], bank.stamp(surfaces))
                result = rollout(game, surfaces["public_root"], policy)
            results.append(dict(id=case["id"], root_sha256=item["root_sha256"], **result))
            bank.atomic(output / "public-target.json", dict(
                baseline_sha256=hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
                versions=versions, rows=results))


if __name__ == "__main__":
    main()


