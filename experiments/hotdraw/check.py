"""Run the bounded HotDraw fixture suite in isolated frozen-runtime processes."""
import argparse
import json
from pathlib import Path
import subprocess
from build import checksum

HERE = Path(__file__).resolve().parent


def card(card_id, pile="Hand", *, upgrade=0, count=1, enchantment=None):
    row = {"cardId": card_id, "pile": pile, "upgradeLevels": upgrade, "count": count}
    if enchantment:
        row["enchantmentId"] = enchantment
    return row


def request(name, cards, *, hp=100, energy=3, powers=(), relics=()):
    return {
        "schemaVersion": 1, "scenarioId": f"HOTDRAW-{name.upper()}", "seed": "HOTDRAW1131",
        "characterId": "IRONCLAD", "encounterId": "FUZZY_WURM_CRAWLER_WEAK",
        "enemyCurrentHp": hp, "initialEnemyMaxHps": [max(50, hp)],
        "initialPlayerHp": 70, "initialPlayerMaxHp": 80, "initialPlayerEnergy": energy,
        "clearPlayerPiles": True, "clearAllPowers": True,
        "cards": cards, "powers": [{"powerId": power, "target": "Player", "amount": 1} for power in powers],
        "relics": [{"relicId": relic} for relic in relics],
    }


def fixtures(upstream_tree):
    flash = card("FLASH_OF_STEEL")
    shrug = card("SHRUG_IT_OFF")
    draw = [card("STRIKE_IRONCLAD", "Draw"), card("DEFEND_IRONCLAD", "Draw")]
    return {
        "draws": request("draws", [card("POMMEL_STRIKE", upgrade=1), flash,
                                  card("STRIKE_IRONCLAD", "Draw", count=2), draw[1]]),
        "nested": request("nested", [card("PREPARED"), card("DEFEND_IRONCLAD"),
                                    card("VOID", "Draw"), draw[0], card("FLASH_OF_STEEL", "Draw")],
                          powers=["ITERATION_POWER"]),
        "exhaust": request("exhaust", [card("BURNING_PACT"), card("DEFEND_IRONCLAD"),
                                      card("STRIKE_IRONCLAD"), *draw, card("FLASH_OF_STEEL", "Draw")],
                           powers=["DARK_EMBRACE_POWER"]),
        "shuffle": request("shuffle", [shrug, card("STRIKE_IRONCLAD", "Discard", count=2),
                                       card("DEFEND_IRONCLAD", "Discard")], relics=["THE_ABACUS"]),
        "shuffle_multi": request("shuffle_multi", [card("POMMEL_STRIKE", upgrade=1),
            card("STRIKE_IRONCLAD", "Discard"), card("DEFEND_IRONCLAD", "Discard"),
            card("FLASH_OF_STEEL", "Discard")]),
        "turn": request("turn", [card("STRIKE_IRONCLAD"), card("STRIKE_IRONCLAD", "Draw", count=4),
                                draw[1], card("FLASH_OF_STEEL", "Draw")]),
        "order": request("order", [flash, *draw], hp=9, energy=1),
        "known": request("known", [card("HEADBUTT"), flash, draw[1], card("STRIKE_IRONCLAD", "Discard")],
                         hp=17, energy=2),
        "energy": request("energy", [card("BLOODLETTING"), flash, *draw], hp=9, energy=0),
        "plain": request("plain", [card("STRIKE_IRONCLAD")], hp=6, energy=1),
        "pair": json.loads((upstream_tree / "coverage/fixtures/search/two-card-infinite-0170.json")
                           .read_text(encoding="utf-8")),
        "unsupported": request("unsupported", [card("HAVOC"), shrug, *draw], powers=["CONFUSED_POWER"]),
        "no_draw": request("no_draw", [shrug, *draw], powers=["NO_DRAW_POWER"]),
        "empty": request("empty", [shrug]),
        "perfect_fit": request("perfect_fit", [shrug, card("STRIKE_IRONCLAD", "Discard", enchantment="PERFECT_FIT"),
                                             card("DEFEND_IRONCLAD", "Discard")]),
    }


def run(build_path, output, names):
    build_path = build_path.resolve()
    build = json.loads(build_path.read_text(encoding="utf-8"))
    for field, identity in (("runtime", "runtime_sha256"), ("dll", "harness_sha256"), ("solver", "solver_sha256")):
        if checksum(Path(build[field])) != build[identity]:
            raise ValueError(f"HotDraw build identity changed: {field}")
    upstream_tree = build_path.parent / f"CombatSolver-{build['upstream']}"
    cases = fixtures(upstream_tree)
    if set(names) - cases.keys():
        raise SystemExit(f"Unknown cases: {sorted(set(names) - cases.keys())}")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    evidence = {}
    errors = {}
    for name in names or cases:
        case = output / name
        case.mkdir()
        request_path = case / "request.json"
        request_path.write_text(json.dumps(cases[name], indent=2), encoding="utf-8")
        result = case / "result.json"
        with (case / "run.log").open("wb") as log:
            try:
                child = subprocess.run(
                    [build["runtime"], build["dll"], "--hotdraw", name, str(request_path), str(result)],
                    cwd=upstream_tree, stdout=log, stderr=subprocess.STDOUT, timeout=35, check=False,
                )
                if child.returncode != 0:
                    errors[name] = f"exit {child.returncode}"
                else:
                    evidence[name] = json.loads(result.read_text(encoding="utf-8"))
            except subprocess.TimeoutExpired:
                errors[name] = "35 s fixture timeout"
        print(f"{name}: {errors.get(name, 'passed')}", flush=True)
    data = {"schema": 1, "build": {key: value for key, value in build.items()
                                    if key not in {"runtime", "dll", "solver"}},
            "fixtures": evidence, "errors": errors}
    (output / "results.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return bool(errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("fixture", nargs="*")
    args = parser.parse_args()
    raise SystemExit(run(args.build, args.output, args.fixture))
