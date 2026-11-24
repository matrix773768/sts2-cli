"""Index a completed campaign and extract its fixed-world diagnostic decisions."""
import argparse
from contextlib import closing
from itertools import islice
import json
from pathlib import Path
import sqlite3

import torch

from loop_battle import read_ledger
from loop_common import HERE, ROOT, checksum, digest
from loop_policy import NetworkPolicy
from loop_roots import composition, reserved


BASELINE = "20204548503051afb234a3581a6647964089e0f5"
GENERATIONS = ("D1", "D2", "S1", "S2")


def load(path):
    return json.loads(path.read_bytes())


def indexed(path):
    display = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    return {"path": display.as_posix(), "sha256": checksum(path)}


def ledger(path, expected=None, ordinals=None, manifest=None):
    database = path / "results.sqlite"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as con:
        identity, contract = con.execute("SELECT sha,json FROM contract").fetchone()
        seen = [row[0] for row in con.execute("SELECT ordinal FROM results ORDER BY ordinal")]
        sessions, wall = con.execute("SELECT count(*),sum(seconds) FROM sessions").fetchone()
    contract = json.loads(contract)
    report = load(path / "summary.json")
    count = len(seen)
    if digest(contract) != identity or count != report["attempts"] or seen != (
            list(range(count)) if ordinals is None else sorted(ordinals)):
        raise ValueError(f"Inconsistent completed ledger at {path}")
    if expected is not None and count != expected:
        raise ValueError(f"Unexpected number of roots at {path}")
    if manifest is not None and contract["manifest"] != manifest:
        raise ValueError(f"Ledger used a different cohort at {path}")
    return dict(database=indexed(database), summary=indexed(path / "summary.json"), identity=identity,
                attempts=count, sessions=sessions, wall_s=wall, outcomes=report["status"],
                behavior=digest(contract["definition"]))


def case_rows(artifact, models, lock, host, cfg):
    result = {}
    for directory in sorted((artifact / "diagnostics").iterdir()):
        if not directory.is_dir():
            continue
        name = directory.name.split("-", 1)[1]
        arm = lock["arms"][name]
        model = None
        if arm["weight"]:
            model = NetworkPolicy(models[arm["weight"]], arm["condition"], arm["budget"], 0., host, cfg)
        rows = []
        for item in read_ledger(directory):
            row = item["row"]
            first = row["steps"][0] if row["steps"] else None
            initial = None
            move = first["action"] if first else None
            card = (first["observation"]["hand"][move["card"]]["id"]
                    if move and move["kind"] == "play_card" else None)
            if model and first:
                view, selected = first["observation"], first["action"]["index"]
                feature = model.encoder.encode(view, model.encoder.initial_history()) | {"policy": model.slot}
                values, probability = next(model.forward([([feature],)]))[0]
                initial = dict(direct_index=int(values.argmax()), executed_index=selected,
                               death_probability=float(probability[selected, 0]), utility=float(values[selected]))
            rows.append(dict(ordinal=item["ordinal"], encounter=row["root"]["encounter"], status=row["status"],
                             length=row["length"], terminal=row["terminal"], initial_q=initial,
                             actual_first=move, first_card=card,
                             first_search=item["search"][0] if item["search"] else None, counts=item["counts"]))
        source = "long" if directory.name.startswith("long-") else "owl"
        ordinals = [job[0] for job in load(artifact / "diagnostics" / f"{source}.json")["jobs"]]
        result[directory.name] = dict(ledger=ledger(directory, ordinals=ordinals), rows=rows)
    return result


def repeat_check(artifact, arm, budget, count):
    initial = read_ledger(artifact / "pretest" / f"budget-{budget}")
    repeat = islice(read_ledger(artifact / "evaluation/development" / arm), count)
    actions, outcomes, terminal = [], [], []
    for a, b in zip(initial, repeat, strict=True):
        left, right = a["row"], b["row"]
        if a["ordinal"] != b["ordinal"] or left["root"] != right["root"]:
            raise ValueError(f"Repeated {arm} runs do not share the same root")
        if [step["action"] for step in left["steps"]] != [step["action"] for step in right["steps"]]:
            actions.append(a["ordinal"])
        if left["status"] != right["status"]:
            outcomes.append(a["ordinal"])
        if left["terminal"] != right["terminal"]:
            terminal.append(a["ordinal"])
    return dict(roots=count, action_changes=actions, outcome_changes=outcomes, terminal_changes=terminal)


def root_isolation(artifact, names):
    families, seeds, _ = reserved()
    initial = dict(historical_deck_compositions=len(families), historical_seeds=len(seeds))
    running = 0
    for name in names:
        jobs = load(artifact / "roots" / f"{name}.json")["jobs"]
        for _, recipe, *_ in jobs:
            family, seed = composition(recipe), recipe["seed"]
            if family in families or seed in seeds:
                raise ValueError(f"Duplicate seed or deck composition in {name}")
            families.add(family)
            seeds.add(seed)
        running += len(jobs)
    return initial | {"new_unique_roots": running}


def check_archive(path, epoch, policy, parent, optimizer, report):
    weights, best, last = (torch.load(path / name, map_location="cpu", weights_only=True)
                           for name in ("best.pt", "best-train.pt", "resume.pt"))
    if (weights["epoch"] != epoch or best["epoch"] != epoch or last["epoch"] != report["epochs"]
            or last["updates"] != report["updates"] or weights["policies"][-1] != policy
            or weights["identity"] != best["identity"] or weights["identity"] != last["identity"]
            or best["identity"]["parent"] != parent or best["identity"]["optimizer"] != optimizer
            or weights["model"].keys() != best["model"].keys()
            or not all(torch.equal(value, best["model"][name]) for name, value in weights["model"].items())):
        raise ValueError(f"Selected weights or optimizer state differs at {path}")


def audit(artifact, destination):
    identity = load(artifact / "roots/identity.json")
    cfg = identity["config"]
    anchor = load(artifact / "ancestor.json")
    lock = load(artifact / "candidate-lock.json")
    selection = load(artifact / "selection.json")
    root_assets = {key: indexed(artifact / "roots" / f"{key}.json") for key in identity["manifests"]}
    if any(value["sha256"] != identity["manifests"][key] for key, value in root_assets.items()):
        raise ValueError("A frozen root manifest changed")
    if (root_assets["confirmation"]["sha256"] != lock["confirmation"]
            or checksum(artifact / "selection.json") != lock["selection"]):
        raise ValueError("The confirmation lock does not bind the cohort and selection")
    if any(checksum(HERE / name) != sha for name, sha in lock["sources"].items()):
        raise ValueError("A source bound to the confirmation lock changed")
    if any(checksum(ROOT / source) != saved for source, saved in identity["excluded"].items()):
        raise ValueError("A preserved historical root manifest changed")
    models = {anchor["best"]: ROOT / cfg["g0"]}
    generation = {}
    for stage in GENERATIONS:
        path = artifact / "models" / stage
        manifest = artifact / "features" / stage / "manifest.json"
        data, report = load(manifest), load(path / "summary.json")
        weights = indexed(path / "best.pt")
        attempt_count = selection["search_attempts"] if stage.startswith("S") else cfg["experience_roots"][stage]
        experience = ledger(artifact / "experience" / stage, attempt_count, manifest=root_assets[stage]["sha256"])
        selected = min(report["curve"][1:], key=lambda row: row["score"])["epoch"]
        previous = generation[stage[0] + "1"] if stage.endswith("2") else None
        parent = previous["weight"]["sha256"] if previous else anchor["best"]
        optimizer = previous["optimizer"]["sha256"] if previous else anchor["optimizer"]
        continuation = previous["policy"] if previous else anchor["policies"][1]
        if (report["epochs"] != cfg["epochs"] or report["updates"] != cfg["epochs"] * cfg["updates_per_epoch"]
                or sum(report["presents"].values()) != report["updates"] * cfg["batch"]
                or experience["database"]["sha256"] != data["identity"]["ledger"]
                or report["sha"] != weights["sha256"] or lock["arms"][stage]["weight"] != report["sha"]
                or data["policy"] != lock["arms"][stage]["condition"]
                or data["definition"]["model"] != parent or data["definition"]["continuation"] != continuation
                or digest(data["definition"]) != experience["behavior"]):
            raise ValueError(f"Generation {stage} is inconsistent")
        check_archive(path, selected, data["policy"], parent, optimizer, report)
        generation[stage] = dict(experience=experience, complete=data["sizes"]["train"]+data["sizes"]["validation"],
            features=indexed(manifest), policy=data["policy"], definition=data["definition"], selected_epoch=selected,
            updates=report["updates"], presentations=report["presents"],
            weight=weights, optimizer=indexed(path / "best-train.pt"), resume=indexed(path / "resume.pt"),
            report=indexed(path / "summary.json"), log=indexed(path / "train.log"))
        models[report["sha"]] = path / "best.pt"
    phases = {phase: {name: ledger(artifact / "evaluation" / phase / name, count,
                                  manifest=root_assets[phase]["sha256"]) for name in lock["arms"]}
              for phase, count in cfg["cohorts"].items() if phase != "smoke"}
    diagnostics = case_rows(artifact, models, lock, identity["host"], cfg)
    files = ("ancestor.json", "roots/identity.json", "selection.json", "checks/summary.json", "candidate-lock.json",
             "models/D1/interruption-proof.json", "paired.json", "support.json", "diagnostics/owl.json",
             "diagnostics/long.json")
    d1_first = "models/D1/epoch-1-summary.json"
    if (artifact / d1_first).exists():
        files += (d1_first,)
    result = dict(version=cfg["version"], base_commit=BASELINE, game="0.113.1 (26660232)",
                  solver="0.51.5-iik.3b", files={name: indexed(artifact / name) for name in files},
                  roots=root_assets, root_isolation=root_isolation(artifact, root_assets),
                  generations=generation, arms=lock["arms"], runs=phases, diagnostics=diagnostics,
                  pretest={str(b): ledger(artifact / "pretest" / f"budget-{b}", cfg["pretest_roots"])
                           for b in [0, *cfg["budget_candidates"]]},
                  repeated_development={arm: repeat_check(artifact, arm, budget, cfg["pretest_roots"])
                                        for arm, budget in (("D0", 0), ("S0", selection["budget"]))},
                  smoke={arm: ledger(artifact / "smoke" / arm, cfg["cohorts"]["smoke"]) for arm in ("D0", "S0")},
                  sources={path.name: checksum(path) for path in sorted(HERE.iterdir())
                           if (path.suffix == ".py" or path.name in ("config.json", ".gitattributes"))})
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8", newline="\n")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("campaign", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    torch.set_num_threads(2)
    audit(args.campaign.resolve(), args.output.resolve())
