"""Generate, fit, compare and harvest an append-only LS1 search ledger."""
import argparse
from collections import Counter
from math import isfinite
from pathlib import Path
from time import monotonic, perf_counter

import numpy as np

from ls1_design import HERE, PROTOCOL, STRATEGIES, manifest, verify_groups, read, digest
from search import bank, f3a, ms, restore, search, semantic, setup
import model

MODES = ("baseline_search", "statistics", "card_id", "learned_search")
RECORD_SCHEMA = "sts2.m1-ls1.experience.v1"
EVIDENCE = "research_prediction_hidden_rng"
STOP_RUN = bank.f1.i2.StopRun


def experience(case, versions, public, gaps, mode, result, bundle=None, fallback=None):
    run_version = bundle["sha256"] if bundle and mode in ("card_id", "learned_search") else None
    consumed = 0
    attempts = result["attempts"]
    for index, attempt in enumerate(attempts):
        attempt["allocated_limit"] = result["first_cap"] - consumed
        consumed += attempt["transitions"]
        if attempt["transitions"] > attempt["allocated_limit"] or consumed != attempt["at"]:
            raise ValueError("Candidate accounting differs from actual scheduler")
        verified = index == len(attempts) - 1 and result["first_locked"] is not None
        attempt.update(verified_win=verified, locked=result["first_locked"] if verified else None,
                       first_cost=consumed if verified else None)
    return dict(schema=RECORD_SCHEMA, model_input=public, versions=versions | {"encoder": model.ENCODER},
                outcome=result, audit=dict(id=case["id"], split=case["split"], source=case["source"],
                natural_reachability=case["natural_reachability"], family=case["family"],
                pair=case["pair"], history=case["history"], recipe=case["recipe"],
                root_stamp=result.pop("root_stamp"), mode=mode, model_sha256=run_version,
                root_spec_sha256=digest(case), evidence=EVIDENCE, fallback=fallback, public_gaps=gaps))


def specs(phase, case):
    if phase in ("pilot", "report"):
        arms = ("baseline_search",) if phase == "pilot" else MODES
        for cap in PROTOCOL["budgets"]:
            # Counterbalance RPC order deterministically across roots and budgets.
            offset = (int(digest(case["id"])[:8], 16) + cap // 64) % len(arms)
            for mode in arms[offset:] + arms[:offset]:
                yield mode, int(cap * PROTOCOL["first_win_fraction"]), cap, None
    if phase in ("pilot", "collect"):
        cap = PROTOCOL["teacher_first_cap"]
        for strategy in STRATEGIES:
            yield "teacher", cap, cap * 2, strategy
    if phase == "feedback":
        cap = PROTOCOL["teacher_first_cap"]
        yield "learned_search", cap, cap * 2, None


def load_model(path, strict=False):
    if not path.is_file():
        if strict:
            raise ValueError("A frozen fitted model is required")
        return None
    try:
        payload = read(path)
        sha = payload["sha256"]
        if digest({k: v for k, v in payload.items() if k != "sha256"}) != sha:
            raise ValueError("Model digest differs")
        if payload["protocol"] != digest(PROTOCOL):
            raise ValueError("Model protocol differs")
        models = {}
        for mode in model.MODES:
            templates = payload["models"][mode]["parameters"]
            if len(templates) != len(PROTOCOL["training"]["seeds"]):
                raise ValueError("Unexpected ensemble size")
            models[mode] = [
                {k: np.asarray(v, dtype=float) for k, v in row.items()} for row in templates
            ]
        return payload | {"models": models}
    except (KeyError, TypeError, ValueError, OSError):
        if strict:
            raise
        return None


def cell(game, case, public, gaps, versions, bundle, spec, prep_ms):
    mode, first_cap, cap, teacher = spec
    tick = perf_counter()
    ranked, fallback, model_ms = (STRATEGIES, None, 0.0) if teacher else model.order(
        public, gaps, mode, first_cap, bundle, versions)
    changed = ranked != STRATEGIES
    prep = prep_ms if mode != "baseline_search" and not teacher else 0.0
    ordering_ms = ms(tick) + prep if mode != "baseline_search" and not teacher else 0.0
    result = search(game, first_cap, cap, order=ranked if changed else None, teacher=teacher,
                    ordering_ms=ordering_ms, model_ms=model_ms)
    initial = result["executed_initial"]
    result.update(order_changed=changed, executed_order_changed=(not teacher and initial != list(STRATEGIES[:len(initial)])),
                  candidate_probe=teacher, public_prepare_ms=prep)
    return experience(case, versions, public, gaps, mode, result, bundle, fallback)


def read_records(out, phase, expected, *, required=True):
    directory = out / phase
    rows = [read(path) for path in sorted(directory.glob("*.json"))] if directory.exists() else []
    if required and {r["id"] for r in rows} != {c["id"] for c in expected}:
        raise ValueError(f"Incomplete {phase} ledger")
    return rows


def validate_experiment_rows(records, cases, versions):
    by_id = {case["id"]: case for case in cases}
    seen = set()
    groups = []
    for record in records:
        key = record["id"]
        case = by_id[key]
        if key in seen or record["case_sha256"] != digest(case):
            raise ValueError("Duplicate or foreign root record")
        seen.add(key)
        variants = set()
        for exp in record["experience"]:
            audit = exp["audit"]
            result = exp["outcome"]
            variant = (audit["mode"], result["cap"], result["candidate_probe"])
            if exp["versions"] != versions | {"encoder": model.ENCODER} or variant in variants:
                raise ValueError("Variant or version drift")
            variants.add(variant)
            if (audit["id"] != key or audit["root_spec_sha256"] != digest(case) or
                    any(audit[k] != case[k] for k in ("split", "family", "pair", "history", "recipe", "source"))):
                raise ValueError("Experience linked to wrong root")
            groups.append(case | {"root_stamp": audit["root_stamp"]})
        if len({r["audit"]["root_stamp"] for r in record["experience"]} - {None}) > 1:
            raise ValueError("Prediction root drift between paired runs")
    verify_groups({(c["id"], c.get("root_stamp")): c for c in groups if c.get("root_stamp")}.values())


def collect(out, phase, cases, versions, bundle, deadline):
    focus = {"pilot": {"pilot"}, "collect": {"train", "selection"},
             "report": {"report", "reachable"}, "feedback": {"feedback"}}[phase]
    items = [c for c in cases if c["split"] in focus]
    if sum(s[2] for c in items for s in specs(phase, c)) > PROTOCOL["max_prediction_transitions"][phase]:
        raise ValueError("Requested sample exceeds preregistered Replay budget")
    journal = out / phase
    journal.mkdir(exist_ok=True)
    saved = read_records(out, phase, items, required=False)
    validate_experiment_rows(saved, items, versions)
    if bundle and any(e["audit"]["model_sha256"] != bundle["sha256"]
                      for row in saved for e in row["experience"]
                      if e["audit"]["mode"] in ("card_id", "learned_search")):
        raise ValueError("Existing search records used a different model")
    for index, case in enumerate(items, 1):
        path = journal / (case["id"] + ".json")
        if path.exists():
            continue
        reservation = path.with_suffix(".reserved")
        if monotonic() >= deadline:
            raise TimeoutError(f"{phase} wall budget exhausted before {case['id']}")
        try:
            with reservation.open("x") as stream:
                stream.write(digest(case) + "\n")
        except FileExistsError:
            raise ValueError(f"Interrupted reservation requires a new run directory: {reservation}") from None
        start = perf_counter()
        row = dict(id=case["id"], case_sha256=digest(case), experience=[], failure=None,
                   reachability=case["natural_reachability"], encounter=None, build_ms=None)
        try:
            with restore(out, case, versions, deadline) as (game, public, identity):
                row.update(build_ms=ms(start), encounter=identity["encounter"])
                row["live_stamp"] = identity["live"]
                tick = perf_counter()
                visible = {k: identity["resources"][k] for k in ("potions", "relics")}
                inputs, gaps = model.public_input(public, visible)
                prep = ms(tick)
                for spec in specs(phase, case):
                    if monotonic() >= deadline:
                        raise TimeoutError("Phase deadline")
                    row["experience"].append(cell(game, case, inputs, gaps, versions, bundle, spec, prep))
        except (STOP_RUN, TimeoutError) as error:
            code = getattr(error, "status", None)
            row["failure"] = dict(status="timeout" if isinstance(error, TimeoutError) else code or "engine_error",
                                  detail=str(error), missing_cases=sum(1 for _ in specs(phase, case))
                                  - len(row["experience"]), cost_unknown=True)
        row["root_wall_ms"] = ms(start)
        bank.atomic(path, row)
        print(phase, index, "/", len(items), case["id"], dict(Counter(
            e["outcome"]["status"] for e in row["experience"])), row["failure"] or "", flush=True)
    rows = read_records(out, phase, items)
    validate_experiment_rows(rows, items, versions)
    return rows


def examples(records, split):
    for row in records:
        for exp in row["experience"]:
            audit, outcome = exp["audit"], exp["outcome"]
            if audit["split"] != split or audit["public_gaps"] or outcome["route_risks"]:
                continue
            for index, attempt in enumerate(outcome["attempts"]):
                if (attempt["kind"] != "initial_strategy" or index != 0 or
                        attempt["allocated_limit"] != PROTOCOL["teacher_first_cap"]):
                    continue
                if split == "feedback":
                    if (audit["mode"] != "learned_search" or audit["fallback"] or not audit["model_sha256"]):
                        continue
                elif audit["mode"] != "teacher":
                    continue
                status = attempt["status"]
                if attempt["verified_win"]:
                    terminal = attempt["locked"]
                    utility = .70 + .18 * terminal["hp"] / terminal["max_hp"]
                    utility += .12 * (1 - attempt["first_cost"] / attempt["allocated_limit"])
                elif (status == "death" or status == "truncated"
                      and attempt["detail"] in ("action_cap", "transition_cap")):
                    utility = 0.0
                else:
                    continue
                if not isfinite(utility):
                    raise ValueError("Invalid label")
                yield row["id"], exp["model_input"], attempt["strategy"], attempt["allocated_limit"], utility


def train(out, phase, cases, versions, deadline):
    source = read_records(out, "collect", [c for c in cases if c["split"] in ("train", "selection")])
    validate_experiment_rows(source, cases, versions)
    training = list(examples(source, "train"))
    selection = list(examples(source, "selection"))
    provenance = dict(generation=1, parent=None, collection=digest(source), feedback=None)
    target = out / "model-v1.json"
    if phase == "feedback":
        fresh = read_records(out, "feedback", [c for c in cases if c["split"] == "feedback"])
        validate_experiment_rows(source + fresh, cases, versions)
        old = load_model(target, strict=True)
        if any(e["audit"]["model_sha256"] != old["sha256"]
               for row in fresh for e in row["experience"]):
            raise ValueError("Feedback model attribution differs")
        new_examples = list(examples(fresh, "feedback"))
        if not new_examples:
            raise ValueError("Feedback ledger has no eligible new observations")
        training.extend(new_examples)
        provenance.update(generation=2, parent=old["sha256"], feedback=digest(fresh))
        target = out / "model-v2.json"
    if target.exists():
        locked = load_model(target, strict=True)
        if locked["versions"] != model.model_versions(versions) or locked["provenance"]["collection"] != digest(source):
            raise ValueError("Existing model has incompatible versions or training ledger")
        if phase == "feedback" and locked["provenance"]["feedback"] != provenance["feedback"]:
            raise ValueError("Existing model has incompatible feedback ledger")
        return
    provenance.update(train_rows=len(training), selection_rows=len(selection),
                      train_roots=len({e[0] for e in training}), selection_roots=len({e[0] for e in selection}))
    fit_deadline = perf_counter() + max(0, deadline - monotonic())
    bundle = model.fit(training, selection, versions, fit_deadline, provenance)
    bank.atomic(target, bundle)
    print("frozen", target.name, bundle["sha256"], provenance, flush=True)


def check_inference(out, cases, versions, bundle):
    source = read_records(out, "collect", [c for c in cases if c["split"] in ("train", "selection")])
    example = next(examples(source, "train"), None)
    if example is None:
        raise ValueError("Expected eligible training evidence for inference preflight")
    _, state, _, cap, _ = example
    for mode in ("card_id", "learned_search"):
        order, reason, _ = model.order(state, [], mode, cap, bundle, versions)
        if reason or len(order) != len(STRATEGIES) or set(order) != set(STRATEGIES):
            raise ValueError(f"Model inference preflight failed for {mode}: {reason}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "pilot", "collect", "train", "report", "feedback"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    phase, out = args.phase, args.output.resolve()
    started = monotonic()
    deadline = started + PROTOCOL["phase_wall_seconds"][phase]
    out.mkdir(parents=True, exist_ok=True)
    with bank.writer(out):
        versions = setup(out, phase == "freeze")
        cases = manifest()
        if phase == "freeze":
            if (out / "baseline.json").exists():
                raise ValueError("Baseline is already frozen")
            rows = []
            for case in (c for c in cases if c["split"] == "pilot"):
                with restore(out, case, versions, deadline) as (game, _, _):
                    for cap in PROTOCOL["budgets"]:
                        rows.append(dict(id=case["id"], result=semantic(search(game, cap//2, cap))))
            bank.atomic(out / "baseline.json", dict(versions=versions, rows=rows))
            return
        contract = dict(protocol=PROTOCOL, versions=versions, manifest=cases, encoder=model.ENCODER)
        contract_file = out / "contract.json"
        if contract_file.exists() and read(contract_file) != contract:
            raise ValueError("Experiment contract changed")
        if not contract_file.exists():
            bank.atomic(contract_file, contract)
        if phase == "train":
            if (out / "report").exists() and not (out / "model-v1.json").exists():
                raise ValueError("Report opened before model freeze")
            train(out, phase, cases, versions, deadline)
        else:
            bundle = load_model(out / "model-v1.json", strict=True) if phase in ("report", "feedback") else None
            if bundle:
                check_inference(out, cases, versions, bundle)
            rows = collect(out, phase, cases, versions, bundle, deadline)
            if phase == "pilot":
                pinned = {(r["id"], r["result"]["cap"]): r["result"] for r in read(HERE / "baseline.json")["rows"]}
                for root in rows:
                    for exp in root["experience"]:
                        if exp["audit"]["mode"] == "baseline_search":
                            cell_result = exp["outcome"] | {"root_stamp": exp["audit"]["root_stamp"]}
                            if semantic(cell_result) != pinned.pop((root["id"], cell_result["cap"])):
                                raise ValueError("Opt-out differs from frozen F3B C/F4 baseline")
                if pinned:
                    raise ValueError("Incomplete opt-out differential")
            if phase == "feedback":
                train(out, phase, cases, versions, deadline)
        elapsed = out / (phase + "-duration.json")
        if not elapsed.exists():
            bank.atomic(elapsed, dict(seconds=monotonic()-started))


if __name__ == "__main__":
    main()
