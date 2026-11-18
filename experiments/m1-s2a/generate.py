"""Generate a small deterministic synthetic cohort and verify it in native processes."""
import argparse
from collections import Counter
from pathlib import Path
import random
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-s1"))
import run as synth

bank = synth.bank
HOST = "m1-s2a-build"
VERSION = "m1-s2a-v1"


def bounds(profile, key, lower, upper):
    values = profile[key]
    if (not isinstance(values, list) or len(values) != 2 or any(type(v) is not int for v in values)
            or not lower <= values[0] <= values[1] <= upper):
        raise ValueError(f"Invalid {key} bounds")
    return values


def sufficient_copies(rule, counts, slots):
    """Check each pool and their union after accounting for shared candidates."""
    attack, guard = set(rule["attack"]), set(rule["guard"])
    capacity = {card: 2 - counts[card] for card in attack | guard}
    return (sum(capacity[card] for card in attack) >= (slots + 1) // 2
            and sum(capacity[card] for card in guard) >= slots // 2
            and sum(capacity.values()) >= slots)


def generate_case(plan, name, profile_name, native, *, instance=None):
    rule, profile = plan["rules"][name], plan["profiles"][profile_name]
    key = f"{name}-{profile_name}"
    seed_fields = [VERSION, plan["generator_seed"], name, profile_name]
    if instance is not None:
        seed_fields.extend(instance)
    case_seed = int(bank.stamp(seed_fields)[:16], 16)
    rng = random.Random(case_seed)
    character = next((c for c in native["characters"] if c["name"] == rule["character"]), None)
    if character is None:
        raise ValueError(f"{key}: unsupported native character")
    models = {card["id"]: card for card in character["cards"]}
    for group, allowed in (("anchors", {"Attack", "Skill", "Power"}), ("attack", {"Attack"}),
                           ("guard", {"Attack", "Skill"})):
        candidates = rule[group]
        if (not candidates or len(set(candidates)) != len(candidates)
                or any(models.get(card, {}).get("type") not in allowed or
                       models[card]["rarity"] not in {"Common", "Uncommon", "Rare"}
                       for card in candidates)):
            raise ValueError(f"{key}: unregistered or incompatible native card in {group}: {candidates}")
    starter = Counter(character["starter"])
    keep = Counter(rule["keep"])
    if keep - starter:
        raise ValueError(f"{key}: requested keep card is outside the native starter")
    basics = {card: "attack" if models[card]["type"] == "Attack" else "guard"
              for card in starter if models[card]["rarity"] == "Basic" and starter[card] >= 2}
    if set(basics.values()) != {"attack", "guard"} or len(basics) != 2:
        raise ValueError(f"{key}: unexpected native starter shape")

    size = rng.randint(*bounds(profile, "deck", 12, 22))
    deck = [*rule["keep"], *rule["anchors"]]
    counts = Counter(rule["anchors"])
    slots_to_fill = size // 2 - len(rule["anchors"])
    for position in range(slots_to_fill):
        role = "attack" if position % 2 == 0 else "guard"
        eligible = [c for c in rule[role] if counts[c] < 2]
        if not eligible:
            raise ValueError(f"{key}: {role} pool exhausted under the two-copy ceiling")
        choice = rng.choice(eligible)
        if instance is not None:
            remaining = slots_to_fill - position - 1
            next_rule = rule if role == "guard" else rule | {"attack": rule["guard"], "guard": rule["attack"]}
            def feasible(card):
                return sufficient_copies(next_rule, counts + Counter({card: 1}), remaining)
            if not feasible(choice):
                feasible_cards = [card for card in eligible if feasible(card)]
                if not feasible_cards:
                    raise ValueError(f"{key}: insufficient native cards for the remaining role slots")
                choice = rng.choice(feasible_cards)
        deck.append(choice)
        counts[choice] += 1
    deck.extend(card for card in basics for _ in range(2))
    remaining = [card for card in basics for _ in range(starter[card] - 2)]
    if not 0 <= size - len(deck) <= len(remaining):
        raise ValueError(f"{key}: invalid deck size for the native starter")
    deck.extend(rng.sample(remaining, size - len(deck)))
    rng.shuffle(deck)
    upgrade_count = rng.randint(*bounds(profile, "upgrades", 0, size))
    upgradable = [i for i, card in enumerate(deck) if models[card]["upgradable"]]
    if upgrade_count > len(upgradable):
        raise ValueError(f"{key}: native upgrade pool exhausted")
    upgrades = set(rng.sample(upgradable, upgrade_count))

    variant = next((a for a in native["acts"] if a["act"] == profile["act"]
                    and a["variant"] == profile["act_variant"]), None)
    encounters = profile["encounters"]
    if (not variant or not encounters or set(encounters) - {
            e["id"] for e in variant["encounters"] if e["room"] == "Monster"}):
        raise ValueError(f"{key}: encounter outside the native ordinary act variant")
    potions = profile["potion_options"]
    if not potions or set(potions) - {None, *native["potions"]}:
        raise ValueError(f"{key}: potion unavailable in the native catalog")

    potion = rng.choice(potions)
    slots = [None] * character["slots"]
    if potion:
        slots[rng.randrange(len(slots))] = potion
    max_hp = character["max_hp"]
    percent = rng.randint(*bounds(profile, "hp_percent", 1, 100))
    spec = dict(schema=2, character=character["name"], ascension=0, act=variant["act"],
                act_variant=variant["variant"], encounter=rng.choice(encounters),
                seed=f"{rng.getrandbits(48):012X}", hp=max(1, max_hp * percent // 100), max_hp=max_hp,
                relics=character["relics"] if profile["starter_relic"] else [], potions=slots,
                deck=[dict(id=card, upgrade=int(i in upgrades)) for i, card in enumerate(deck)])
    return dict(case=key, generator=VERSION, generator_seed=plan["generator_seed"],
                rule=name, profile=profile_name, case_seed=case_seed, tags=rule["tags"],
                parameters=dict(deck_size=size, upgrades=upgrade_count, hp_percent=percent,
                                starter_relic=profile["starter_relic"], potion=potion),
                spec=spec, spec_sha256=bank.stamp(spec))


def generate(plan, native):
    if plan["schema"] != 1 or not 1 <= len(plan["rules"]) * len(plan["profiles"]) <= 24:
        raise ValueError("Expected a v1 plan of at most 24 cases")
    cases = [generate_case(plan, rule, profile, native)
             for rule in plan["rules"] for profile in plan["profiles"]]
    ids = {c["case"] for c in cases}
    if len(ids) != len(cases) or set(plan["f3b_cases"]) - ids or len(set(plan["f3b_cases"])) > 8:
        raise ValueError("Invalid case names or F3B selection")
    return cases


def deduplicate(records, key):
    seen = set()
    unique = []
    duplicates = []
    for row in records:
        digest = row[key]
        if digest in seen:
            duplicates.append(row["case"])
        else:
            seen.add(digest)
            unique.append(row)
    return unique, duplicates


def run(output, plan):
    sys.addaudithook(synth.f3b.deny_reference_open)
    versions = bank.versions_for_host(output, HOST) | {"synthetic_spec": 2, "initializer": VERSION}
    clock = perf_counter()
    with synth.new_session(output) as game:
        catalog = game.request("synthetic_catalog")
        catalog_peak = game.report["peak_working_set_bytes"]
    catalog_ms = bank.elapsed(clock)
    bank.atomic(output / "catalog.json", catalog)
    clock = perf_counter()
    cases = generate(plan, catalog)
    generation_ms = bank.elapsed(clock)
    cases, duplicate_specs = deduplicate(cases, "spec_sha256")

    # Re-query the native catalog in a separate process, then independently regenerate a fixed sample.
    with synth.new_session(output) as game:
        second_catalog = game.request("synthetic_catalog")
    synth.f3a.equal("independent native catalog", catalog, second_catalog)
    picked = random.Random(plan["repeat_seed"]).sample(cases, plan["repeat_count"])
    repeats = [generate_case(plan, row["rule"], row["profile"], second_catalog) for row in picked]
    synth.f3a.equal("independent generated configs", picked, repeats)
    synth.f3a.equal("repeated spec dedup", [r["case"] for r in picked],
                   deduplicate(cases + repeats, "spec_sha256")[1])

    # Publish the generated cohort and selection before invoking any solver.
    bank.atomic(output / "cohort.json", dict(plan_sha256=bank.stamp(plan), cases=cases,
                                            f3b_selection=plan["f3b_cases"]))
    records, failures = [], []
    for case in cases:
        try:
            root, audit = synth.verified_variant(output, case["spec"], versions)
        except synth.f3a.Difference as error:
            failures.append(case | dict(status="strict_difference", phase=error.phase,
                expected_sha256=bank.stamp(error.expected), actual_sha256=bank.stamp(error.actual)))
            continue
        except bank.ERRORS as error:
            failures.append(case | bank.failure(error))
            continue
        records.append(case | dict(root=root, audit=audit, live=root["identity"]["live"], f3b=None))
        print(case["case"], "native verified", root["identity"]["live"][:12], flush=True)
    records, duplicate_live = deduplicate(records, "live")

    for row in records:
        if row["case"] not in plan["f3b_cases"]:
            continue
        stage = output / row["case"]
        stage.mkdir()
        start = perf_counter()
        report = synth.verify_f3b(stage, row["root"])
        if report.get("detail", "").startswith("PredictionUnsupportedException:"):
            report["status"] = "unsupported_prediction"
        row["f3b"] = report | {"elapsed_ms": bank.elapsed(start)}
        print(row["case"], report["status"], report.get("transitions"), flush=True)

    save_files = [p for p in output.rglob("*") if p.is_file() and p.suffix.lower() in {".save", ".mcr"}]
    synth.f3a.equal("no native save or replay output", [], save_files)
    bank.atomic(output / "records.json", dict(schema=1, generator=VERSION, plan_sha256=bank.stamp(plan),
        catalog_sha256=bank.stamp(catalog), versions=versions, cases=records, failures=failures,
        f3b_selection=plan["f3b_cases"], repeated_cases=[r["case"] for r in repeats],
        duplicate_specs=duplicate_specs, duplicate_live=duplicate_live, native_save_or_replay_files=0,
        catalog_ms=catalog_ms, catalog_peak_working_set_bytes=catalog_peak, generation_ms=generation_ms))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--plan", type=Path, default=HERE / "plan.json")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    run(output, bank.read(args.plan))


if __name__ == "__main__":
    main()
