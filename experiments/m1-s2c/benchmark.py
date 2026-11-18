"""Run and audit the fixed S2C paired benchmark without opening test root archives."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from time import perf_counter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("s2c_factory", HERE.parent / "m1-s2b/factory.py")
s2b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s2b)
bank, f3a, f3b = s2b.bank, s2b.f3a, s2b.f3b
INDEX = HERE.parent / "m1-s2b/index.json"
SELECTION = HERE / "selection.json"
SEED = "m1-s2c-stratified-v1"
POLICY = ("f3b", "f4")
SPLITS = ("development", "validation")
FIELDS = ("id", "root_id", "live", "spec_sha256", "split", "rule", "character",
          "act", "act_variant", "encounter", "profile", "seed", "hp")


def freeze(index):
    groups = defaultdict(list)
    for row in index["rows"]:
        if (row["split"] in SPLITS and row["status"] == "verified"
                and row["id"] not in index["evaluation_ids"]):
            groups[row["split"], row["encounter"], row["rule"]].append(row)
    selected, counts = [], Counter()
    for (split, _, _), rows in sorted(groups.items()):
        row = min(rows, key=lambda r: (counts[split, r["profile"]], bank.stamp([SEED, r["id"]])))
        counts[split, row["profile"]] += 1
        selected.append({key: row[key] for key in FIELDS})
    if Counter(r["split"] for r in selected) != dict(development=32, validation=16):
        raise ValueError("Frozen selection must have one root per encounter/rule stratum")
    pilot = []
    for encounter in sorted({r["encounter"] for r in selected if r["split"] == "development"}):
        eligible = [r for r in selected if r["encounter"] == encounter
                    and r["character"] == ("Ironclad" if len(pilot) % 2 == 0 else "Silent")]
        pilot.append(min(eligible, key=lambda row: bank.stamp([SEED, "pilot", row["id"]]))["id"])
    return dict(schema=1, sampler=SEED, source_plan_sha256=index["plan_sha256"],
                source_index_sha256=bank.stamp(index), cap=512, policies=list(POLICY), pilot=pilot,
                selection=selected)


def inputs(directory, selection, subset):
    index = bank.read(INDEX)
    plan = s2b.prepare_plan(directory)
    f3a.equal("S2B source plan", index["plan_sha256"], bank.stamp(plan))
    f3a.equal("selection source", (bank.stamp(index), index["plan_sha256"]),
              (selection["source_index_sha256"], selection["source_plan_sha256"]))
    f3a.equal("unmodified local source index", index, bank.read(directory / "index.json"))
    index_rows = {r["id"]: r for r in index["rows"] if r["split"] in SPLITS and r["status"] == "verified"}
    picked = [r["id"] for r in selection["selection"]]
    if not picked or len(picked) != len(set(picked)) or set(picked) - index_rows.keys():
        raise ValueError("Selection must contain distinct verified development/validation roots")
    if not set(selection["pilot"]) <= set(picked):
        raise ValueError("Pilot must be part of the fixed selection")
    eligible = set(selection["pilot"] if subset == "pilot" else picked)
    cases = {c["id"]: c for c in plan["cases"] if c["id"] in eligible}
    done = {}
    for row in selection["selection"]:
        case_id = row["id"]
        f3a.equal("selected frozen identity", {key: index_rows[case_id][key] for key in FIELDS}, row)
        if case_id not in eligible:
            continue
        artifact = s2b.checked(directory / "roots" / f"{case_id}.json.gz")
        root = artifact["root"]
        f3a.equal("selected archive metadata", (cases[case_id], "verified", row["root_id"],
                  row["live"], plan["versions"], cases[case_id]["spec"], "L0", True, True, "unknown"),
                  (artifact["case"], artifact["status"], root["id"], root["identity"]["live"],
                   root["versions"], root["spec"], root["level"], root["native_verified"],
                   root["synthetic"], root["native_reachable"]))
        f3a.equal("selected continuation", row["live"], bank.f1.digest(root["native"]["continuation"].encode()))
        f3a.equal("selected native key", s2b.native_key(root), artifact["native_key"])
        f3a.equal("two cold rebuilds", 2, len(artifact["audit"]["rebuilds"]))
        done[case_id] = artifact
    return plan, done


def code_id():
    # The evaluator does not change the search algorithms. Pin the Python paths that execute them.
    return bank.stamp([hashlib.sha256(path.read_bytes()).hexdigest() for path in (
        Path(s2b.__file__), Path(s2b.quality.__file__), Path(f3b.__file__), Path(f3a.__file__),
        Path(s2b.synth.__file__), HERE.parent / "m1-f3d-b/verify.py")])


def contract(output, plan, selection, subset, cap, algorithm):
    wanted = dict(source_plan_sha256=bank.stamp(plan), selection_sha256=bank.stamp(selection),
                  subset=subset, cap=cap, algorithm=algorithm, implementation=code_id())
    path = output / "contract.json"
    if path.exists():
        f3a.equal("resume contract", bank.read(path), wanted)
    else:
        bank.atomic(path, wanted)
    return wanted


def collect(output, plan, done, args, frozen):
    clock = perf_counter()
    reason, completed = "complete", []
    preexisting = len(list((output / "labels").glob("*.json.gz")))
    with bank.MemorySampler() as memory, ThreadPoolExecutor(max_workers=args.workers) as pool:
        limits = s2b.Limits(output, args, memory)
        pending = iter(done.values())
        jobs = {}
        try:
            while True:
                while len(jobs) < args.workers and (item := next(pending, None)) is not None:
                    limits.check()
                    key = item["case"]["id"]
                    jobs[key] = pool.submit(s2b.label_one, output, item["case"], item["root"], frozen["cap"],
                                            frozen["algorithm"], limits, frozen["implementation"])
                if not jobs:
                    break
                key = next(iter(jobs))
                labels = s2b.under_budget(limits, jobs.pop(key))
                completed.append(key)
                print(key[:12], done[key]["case"]["split"],
                      "/".join(f"{label['level']}:{label['total_charged']}" for label in labels), flush=True)
        except (s2b.BatchStop, KeyboardInterrupt) as error:
            reason = str(error) if isinstance(error, s2b.BatchStop) else "interrupt"
        finally:
            limits.cancelled.set()
    native_files = s2b.native_files(output)
    f3a.equal("benchmark native filesystem isolation", [], native_files)
    labels = s2b.verify_labels(output, plan, done)
    summary = dict(stop=reason, workers=args.workers, completed=len(completed),
                   labels_before=preexisting, labels_after=len(labels), elapsed_ms=bank.elapsed(clock),
                   peak_working_set_bytes=memory.batch_peak, memory_samples=memory.samples)
    path = output / "sessions.json"
    s2b.bounded_metadata(path, (bank.read(path) if path.exists() else []) + [summary], limits)
    print(json.dumps(summary), flush=True)


def diffs(expected, actual, path="$", limit=24):
    if limit <= 0 or expected == actual:
        return []
    if isinstance(expected, dict) and isinstance(actual, dict):
        changes = []
        for key in sorted(expected.keys() | actual.keys()):
            if key not in expected or key not in actual:
                changes.append({"field": f"{path}.{key}", "missing": "expected" if key not in expected else "actual"})
            elif key == "exact_continuation_state":
                changes.extend(continuation_diffs(expected[key], actual[key], f"{path}.{key}",
                                                 limit - len(changes)))
            else:
                changes.extend(diffs(expected[key], actual[key], f"{path}.{key}", limit - len(changes)))
            if len(changes) >= limit:
                break
        return changes[:limit]
    if isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        changes = []
        for index, (left, right) in enumerate(zip(expected, actual)):
            changes.extend(diffs(left, right, f"{path}[{index}]", limit - len(changes)))
            if len(changes) >= limit:
                break
        return changes[:limit]
    return [{"field": path, "expected": expected, "actual": actual}]


def continuation_diffs(expected, actual, path, limit):
    if expected == actual:
        return []
    def fields(text):
        pairs = [piece.split("=", 1) for piece in re.split(r";(?=[A-Za-z_][A-Za-z_0-9]*=)", text)]
        keys = [pair[0] for pair in pairs]
        if not all(len(pair) == 2 for pair in pairs) or len(keys) != len(set(keys)):
            return None
        return dict(pairs)
    left, right = fields(expected), fields(actual)
    if left is not None and right is not None:
        changes = diffs(left, right, path, limit)
        if changes:
            return changes
    return [{"field": path, "expected_sha256": bank.f1.digest(expected.encode()),
             "actual_sha256": bank.f1.digest(actual.encode()),
             "first_character_offset": next((i for i, (a, b) in enumerate(zip(expected, actual)) if a != b),
                                            min(len(expected), len(actual)))}]


def error_category(status):
    if status in {"transition_cap", "wall_cap", "memory_cap", "budget_exhausted",
                  "prediction_only_budget", "timeout", "time_limit", "engine_timeout"}:
        return "resource_exhaustion"
    if status in {"unsupported", "unsupported_prediction", "root_prediction_mismatch"}:
        return "prediction_compatibility"
    if status in {"execution_fault", "engine_error", "invalid_prediction_frames", "source_mutation",
                  "plan_action_rejected", "root_mismatch"}:
        return "execution_correctness"
    return "search_coverage"


def audit_trial(trial):
    status = trial.get("validation_skipped", trial["status"])
    verification = trial.get("verification")
    if not verification:
        return dict(status=status, phase="search", category=error_category(status),
                    evidence=trial.get("detail") or trial.get("transition_faults") or trial.get("fault"))
    status = verification["status"]
    preparation = verification.get("preparation", {})
    audit = dict(status=status, route=trial.get("winner_key"), matched_actions=verification.get("matched_actions", 0))
    if status == "win":
        return audit | dict(category="strict_win", phase="native_replay")
    if status == "prediction_mismatch":
        difference = verification["first_difference"]
        step = difference["phase"]
        changes = diffs(difference["expected"], difference["actual"])
        trace = verification.get("trace", [])
        last = trace[-1] if trace else {}
        audit.update(phase="native_replay",
                     category="source_difference" if step == "root" else "simulator_difference", first_step=step,
                     action=last.get("native_action"), fields=changes,
                     terminal_window=last.get("terminal_window"))
    elif status in {"search_fixed_prediction_difference", "independent_prediction_rejected"}:
        reason = preparation.get("status", status)
        category = ("prediction_workflow_difference" if status == "search_fixed_prediction_difference"
                    else error_category(reason))
        audit.update(phase="fixed_prediction", category=category, first_step=verification.get("first_difference"),
                     detail=preparation.get("detail") or preparation.get("reason"),
                     rejected_action=preparation.get("rejected_action"), preparation_status=reason)
    else:
        audit.update(phase="native_replay", category=error_category(status), detail=verification.get("detail"),
                     first_step=verification.get("attempted_step"))
    return audit


def verify_output(output, plan, done, frozen):
    labels = s2b.verify_labels(output, plan, done)
    for label in labels.values():
        if label["cap"] != frozen["cap"] or label["implementation"] != frozen["implementation"]:
            raise ValueError("Label is outside the frozen benchmark contract")
        if frozen["algorithm"] == "f3b" and label["policy"] != "f3b":
            raise ValueError("Unexpected F4 label in a control-only evaluation")
    return {(r["case_id"], r["policy"]): r for r in labels.values()}


def record_timings(control):
    trials = control["trials"]
    verifications = [t["verification"] for t in trials if "verification" in t]
    return dict(wall_ms=control["cell"]["wall_ms"], search_ms=control["cell"]["hot_ms"],
                fixed_ms=sum(n.get("preparation", {}).get("elapsed_ms", 0) for n in verifications),
                native_ms=sum(n.get("elapsed_ms", 0) for n in verifications),
                peak_bytes=max([t.get("peak_working_set_bytes") or 0 for t in trials] +
                               [n.get("peak_working_set_bytes") or 0 for n in verifications] +
                               [n.get("preparation", {}).get("peak_working_set_bytes") or 0
                                for n in verifications], default=0) or None)


def compact_diff(audit):
    # Full field values and frames are kept in the label and repro artifacts.
    for field in audit.get("fields", []):
        for key in ("expected", "actual"):
            if key in field and len(json.dumps(field[key], ensure_ascii=False)) > 160:
                field[key] = {"sha256": bank.stamp(field[key])}
    return audit


def row_for(control, label):
    if control is None or label is None:
        return None
    details = [compact_diff(audit_trial(t)) for t in control["trials"]]
    timing = record_timings(control)
    attempts = len([t for t in control["trials"] if "verification" in t])
    refinement = label.get("refinement", {})
    refined_native = [e["native"] for e in label.get("evidence", {}).get("native", [])]
    if refinement:
        attempts += len(refinement["validation"])
        extras = [compact_diff(audit_trial({"status": "predicted_win", "winner_key": e["key"],
                                           "verification": e["native"]}))
                  for e in label.get("evidence", {}).get("native", [])]
        details.extend(extras)
        timing["wall_ms"] += refinement["elapsed_ms"]
        timing["search_ms"] += refinement.get("quality_hot_ms") or 0
        timing["fixed_ms"] += sum(n.get("preparation", {}).get("elapsed_ms", 0) for n in refined_native)
        timing["native_ms"] += sum(n.get("elapsed_ms", 0) for n in refined_native)
        timing["peak_bytes"] = max([timing["peak_bytes"] or 0, refinement.get("quality_peak_bytes") or 0] +
                                   [n.get("peak_working_set_bytes") or 0 for n in refined_native] +
                                   [n.get("preparation", {}).get("peak_working_set_bytes") or 0
                                    for n in refined_native]) or None
    return dict(archive=f"labels/{label['id']}.json.gz", level=label["level"], status=label["status"],
                first_prediction=control["cell"]["first_prediction"],
                first_strict=control["cell"]["first_native"], total_charged=label["total_charged"],
                selected=label["selected"], native_attempts=attempts, timing=timing,
                refinement_status=refinement.get("quality_status"), trials=details,
                branches=dict(Counter(r["stop"] for t in control["trials"] for r in t.get("routes", []))),
                failure_categories=sorted({d["category"] for d in details if d["category"] != "strict_win"}))


def distribution(values):
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    def percentile(frac):
        pos = frac * (len(values) - 1)
        lo = int(pos)
        return round(values[lo] + (pos - lo) * (values[min(lo + 1, len(values) - 1)] - values[lo]), 3)
    return dict(n=len(values), minimum=values[0], p25=percentile(.25), median=percentile(.5),
                p75=percentile(.75), maximum=values[-1])


def wilson(success, total):
    if not total:
        return None
    z = 1.959963984540054
    proportion = success / total
    denom = 1 + z*z/total
    center = (proportion + z*z/(2*total)) / denom
    span = z * ((proportion*(1-proportion) + z*z/(4*total))/total)**.5 / denom
    return [round(max(0, center-span), 4), round(min(1, center+span), 4)]


def overview(rows, names):
    results = {}
    for split in SPLITS:
        cohort = [r for r in rows if r["split"] == split]
        algorithms = {}
        for name in names:
            measured = [r[name] for r in cohort if r.get(name) is not None]
            wins = [r for r in measured if r["level"] == "L3"]
            algorithms[name] = dict(n=len(measured), planned=len(cohort),
                levels={level: sum(r["level"] == level for r in measured) for level in ("L0", "L1", "L2", "L3")},
                wilson95_l3=wilson(len(wins), len(measured)),
                first_prediction=distribution(r["first_prediction"] for r in measured),
                first_strict=distribution(r["first_strict"] for r in wins),
                charged=distribution(r["total_charged"] for r in measured),
                wall_ms=distribution(r["timing"]["wall_ms"] for r in measured),
                peak_bytes=distribution(r["timing"]["peak_bytes"] for r in measured),
                loss=distribution(r["selected"]["resources"]["hp_lost"] for r in wins),
                failed_by_category=dict(Counter(c for r in measured if r["level"] != "L3"
                                                for c in r["failure_categories"])))
        pairs = [r for r in cohort if r.get("f3b") and r.get("f4")]
        agreement = Counter(f"{int(r['f3b']['level'] == 'L3')}{int(r['f4']['level'] == 'L3')}" for r in pairs)
        dual = [r for r in pairs if r["f3b"]["level"] == r["f4"]["level"] == "L3"]
        deltas = [r["f4"]["selected"]["resources"]["hp"] - r["f3b"]["selected"]["resources"]["hp"]
                  for r in dual]
        loss = [r["f3b"]["selected"]["resources"]["hp_lost"] - r["f4"]["selected"]["resources"]["hp_lost"]
                for r in dual]
        results[split] = dict(algorithms=algorithms, pairs={k: agreement[k] for k in ("00", "01", "10", "11")},
                              paired_l3_rate_delta=(agreement["01"]-agreement["10"])/len(pairs) if pairs else None,
                              hp_delta=distribution(deltas), loss_reduced=distribution(loss),
                              hp_improvements=sum(delta > 0 for delta in deltas),
                              wilson95_hp_improvements=wilson(sum(delta > 0 for delta in deltas), len(deltas)))
    return results


def report(output, plan, done, frozen):
    labels = verify_output(output, plan, done, frozen)
    names = ("f3b",) if frozen["algorithm"] == "f3b" else POLICY
    rows = []
    for key, item in done.items():
        case, root = item["case"], item["root"]
        row = dict(id=key, root_id=root["id"], split=case["split"], rule=case["rule"],
                   character=case["spec"]["character"], act=case["spec"]["act"],
                   encounter=case["spec"]["encounter"], profile=case["profile"])
        for name in names:
            row[name] = row_for(labels.get((key, "f3b")), labels.get((key, name)))
        rows.append(row)
    measured = sum(row.get(name) is not None for row in rows for name in names)
    sessions = output / "sessions.json"
    result = dict(schema=1, contract=frozen, versions=plan["versions"],
                  sessions=bank.read(sessions) if sessions.exists() else [],
                  expected_cells=len(rows)*len(names), complete_cells=measured, test_evaluated=0,
                  label_definitions={"L0": "independently reconstructed native root",
                                     "L1": "native outcome for a frozen policy (not evaluated here)",
                                     "L2": "complete predicted win without strict native acceptance",
                                     "L3": "complete win passing independent strict native verification"},
                  offline_oracle=True, uses_hidden_rng=True, active_potions=False,
                  summary=overview(rows, names), rows=rows)
    bank.atomic(output / "report.json", result)
    print(json.dumps({k: result[k] for k in ("expected_cells", "complete_cells", "summary")}), flush=True)


def native_prefix(output, root, trial, limits):
    """Secondary localization only. Search stamps are not full fixed frames."""
    restore = partial(s2b.synth.rebuild, session=limits.factory())
    if any(c["id"] == "NEUTRALIZE" for c in root["spec"]["deck"]):
        restore = partial(s2b.quality.native_neutralize, restore=restore)
    report = dict(status="matched_search_stamps", matched_actions=0)
    try:
        with restore(output, root) as (game, _):
            def stamp(frame):
                return bank.f1.digest(frame[0]["exact_continuation_state"].encode())
            game.teacher_frames = []
            game.teacher_choices = []
            audit_root = game.request("i1_begin")["state"]
            f3a.equal("diagnostic root search stamp", trial["root_stamp"], stamp(audit_root))
            for index, (action, expected) in enumerate(zip(trial["actions"], trial["stamps"], strict=True), 1):
                limits.check(disk=False)
                report["attempted_step"] = index
                response = game.request("i1_step", action=f3b.action_for_wire(action))
                if response["type"] != "i1_state":
                    return report | dict(status="native_action_rejected", action=action, response=response)
                observed = stamp(response["state"])
                if observed != expected:
                    matching = [n["frame"] for n in trial["history"] if n["frame"]["stamp"] == expected]
                    return report | dict(status="search_stamp_mismatch", action=action,
                        expected_sha256=expected, actual_sha256=observed,
                        predicted_compact=matching[0] if matching else None, native_frame=response["state"],
                        terminal=response["terminal"], native_action=response["native_action"])
                report["matched_actions"] += 1
    except f3a.Difference as error:
        report.update(status="probe_source_difference", phase=error.phase,
                      expected=error.expected, actual=error.actual)
    except s2b.ERRORS as error:
        report.update(bank.failure(error))
    return report


def rejected_trials(control, f4):
    for number, trial in enumerate(control["trials"], 1):
        diagnosis = audit_trial(trial)
        if diagnosis["category"] != "strict_win":
            yield "f3b", number, trial, diagnosis
    evidence = f4.get("evidence", {}) if f4 else {}
    prediction = evidence.get("prediction", {})
    candidates = {candidate["key"]: candidate for candidate in prediction.get("candidates", [])}
    for number, row in enumerate(evidence.get("native", []), 1):
        trial = dict(status="predicted_win", winner_key=row["key"], verification=row["native"],
                     actions=candidates[row["key"]]["actions"], stamps=row["stamps"],
                     root_stamp=prediction["root_stamp"], history=prediction["history"])
        diagnosis = audit_trial(trial)
        if diagnosis["category"] != "strict_win":
            yield "f4", number, trial, diagnosis


def audit_case(output, item, control, f4, limits):
    case, root = item["case"], item["root"]
    failures = []
    with TemporaryDirectory(dir=output / ".work") as folder:
        for policy, index, trial, diagnosis in rejected_trials(control, f4):
            actions = trial.get("actions", [])
            prefix = None
            if diagnosis["status"] == "independent_prediction_rejected" and actions:
                prefix = native_prefix(Path(folder), root, trial, limits)
            step = diagnosis.get("first_step")
            if prefix and prefix["status"] in {"search_stamp_mismatch", "native_action_rejected"}:
                step = prefix["attempted_step"]
            if isinstance(step, str) and step.split(":", 1)[0].isdigit():
                step = int(step.split(":", 1)[0])
            count = step if type(step) is int and step > 0 else len(actions)
            failures.append(dict(policy=policy, trial=index, diagnosis=diagnosis, secondary_native_probe=prefix,
                 minimal_action_prefix=actions[:count], expected_search_sha256=trial.get("stamps", [])[:count],
                 fixed_reproduction_actions=actions if diagnosis["phase"] == "fixed_prediction" else None,
                 original_verification=trial.get("verification", {}).get("first_difference")))
    return dict(case_id=case["id"], split=case["split"], root_id=root["id"], live=root["identity"]["live"],
                spec=root["spec"], control_label=control["id"], quality_label=f4["id"] if f4 else None,
                unresolved=control["level"] != "L3", failures=failures)


def diagnostic_audit(output, plan, done, args):
    frozen = bank.read(output / "contract.json")
    labels = verify_output(output, plan, done, frozen)
    selected = []
    for (key, policy), label in labels.items():
        if policy != "f3b":
            continue
        f4 = labels.get((key, "f4"))
        if label["level"] != "L3" or next(rejected_trials(label, f4), None):
            selected.append((key, done[key], label, f4))
    results = output / "audit"
    results.mkdir(exist_ok=True)
    aggregate = []
    clock = perf_counter()
    reason = "complete"
    with bank.MemorySampler() as memory, ThreadPoolExecutor(max_workers=args.workers) as pool:
        limits = s2b.Limits(output, args, memory)
        try:
            pending = selected
            while pending:
                jobs = {}
                for key, item, label, f4 in pending[:args.workers]:
                    path = results / f"{key}.json.gz"
                    if path.exists():
                        old = s2b.checked(path)
                        f3a.equal("cached audit identity", (key, label["id"], f4["id"] if f4 else None),
                                  (old["case_id"], old["control_label"], old["quality_label"]))
                        aggregate.append(old)
                    else:
                        limits.check()
                        jobs[path] = pool.submit(audit_case, output, item, label, f4, limits)
                for path, future in jobs.items():
                    row = s2b.under_budget(limits, future)
                    s2b.archive(path, s2b.envelope(row), limits)
                    aggregate.append(row)
                pending = pending[args.workers:]
        except (s2b.BatchStop, KeyboardInterrupt) as error:
            reason = str(error) if isinstance(error, s2b.BatchStop) else "interrupt"
        finally:
            limits.cancelled.set()
    report = dict(status=reason, cases=len(aggregate), expected=len(selected),
                  unresolved=sum(r["unresolved"] for r in aggregate),
                  expected_unresolved=sum(label["level"] != "L3" for _, _, label, _ in selected),
                  elapsed_ms=bank.elapsed(clock), peak_working_set_bytes=memory.batch_peak, rows=[
        dict(id=row["case_id"], root_id=row["root_id"], split=row["split"], unresolved=row["unresolved"],
             failures=[compact_diff(f["diagnosis"]) | {"policy": f["policy"], "secondary_native_probe": (
                 {k: f["secondary_native_probe"].get(k) for k in ("status", "matched_actions", "attempted_step", "action")}
                 if f["secondary_native_probe"] else None), "repro_actions": len(f["minimal_action_prefix"])}
                       for f in row["failures"]]) for row in aggregate])
    s2b.bounded_metadata(output / "audit.json", report, limits)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}), flush=True)


def recheck(output, plan, done, frozen, args):
    """Re-run a recorded rejected route through the original independent native verifier."""
    labels = verify_output(output, plan, done, frozen)
    selected = []
    for (key, policy), control in labels.items():
        if policy == "f3b":
            f4 = labels.get((key, "f4"))
            selected.extend((key, policy_name, trial, observed)
                            for policy_name, _, trial, observed in rejected_trials(control, f4)
                            if observed.get("route") in args.route)
    if {observed["route"] for _, _, _, observed in selected} != set(args.route):
        raise ValueError("Every --route must identify a rejected prediction in the benchmark")
    output_dir = output / "rechecks"
    output_dir.mkdir(exist_ok=True)
    with bank.MemorySampler() as memory:
        limits = s2b.Limits(output, args, memory)
        for key, policy, trial, original in selected:
            limits.check()
            root = done[key]["root"]
            restore = partial(s2b.synth.rebuild, session=limits.factory())
            if any(c["id"] == "NEUTRALIZE" for c in root["spec"]["deck"]):
                restore = partial(s2b.quality.native_neutralize, restore=restore)
            with TemporaryDirectory(dir=output / ".work") as folder:
                current = f3b.expect_native(Path(folder), root, trial, restore=restore, keep_frames=True)
            observed = audit_trial(trial | {"verification": current})
            identity = ("status", "phase", "first_step", "fields", "terminal_window", "matched_actions")
            matched = all(original.get(k) == observed.get(k) for k in identity)
            row = dict(case_id=key, route=original["route"], policy=policy, repeated=matched,
                       original=original, observed=observed)
            s2b.archive(output_dir / f"{key}-{policy}-{row['route']}.json.gz", s2b.envelope(row), limits)
            print(json.dumps({"route": row["route"], "repeat_match": matched,
                              "first_step": observed.get("first_step")}), flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("operation", choices=("freeze", "run", "report", "audit", "recheck"))
    cli.add_argument("output", type=Path)
    cli.add_argument("--bank", type=Path, default=ROOT / "logs/m1-s2b/formal")
    cli.add_argument("--selection", type=Path, default=SELECTION)
    cli.add_argument("--route", action="append", default=[], help="Rejected route digest to independently recheck")
    cli.add_argument("--subset", choices=("pilot", "all"), default="all")
    cli.add_argument("--algorithm", choices=("f3b", "f4", "compare"), default="compare")
    cli.add_argument("--budget", type=int, choices=range(1, 2049), metavar="1..2048")
    cli.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    cli.add_argument("--memory-mib", type=int, default=1400)
    cli.add_argument("--disk-mib", type=int, default=512)
    cli.add_argument("--case-seconds", type=int, default=180)
    cli.add_argument("--batch-seconds", type=int, default=1200)
    args = cli.parse_args()
    if args.operation == "freeze":
        if args.output.exists():
            cli.error("freeze requires a new output file")
        bank.atomic(args.output, freeze(bank.read(INDEX)))
        return
    if min(args.memory_mib, args.disk_mib, args.case_seconds, args.batch_seconds) <= 0:
        cli.error("resource limits must be positive")
    if args.output.resolve() == args.bank.resolve() or args.bank.resolve() in args.output.resolve().parents:
        cli.error("benchmark output must be separate from the frozen bank")
    selection = bank.read(args.selection)
    plan, done = inputs(args.bank, selection, args.subset)
    output = args.output.resolve()
    if args.operation == "run":
        for name in ("labels", ".work"):
            (output / name).mkdir(parents=True, exist_ok=True)
    with bank.writer(output):
        frozen = contract(output, plan, selection, args.subset, args.budget or selection["cap"], args.algorithm)
        if args.operation in {"run", "audit", "recheck"}:
            versions = bank.versions_for_host(output, s2b.quality.HOST) | {
                "synthetic_spec": 2, "initializer": "m1-s2a-v1"}
            f3a.equal("frozen benchmark host", plan["versions"], versions)
        if args.operation == "run":
            collect(output, plan, done, args, frozen)
        elif args.operation == "audit":
            diagnostic_audit(output, plan, done, args)
        elif args.operation == "recheck":
            if not args.route:
                cli.error("recheck requires one or more --route digests")
            recheck(output, plan, done, frozen, args)
        else:
            report(output, plan, done, frozen)


if __name__ == "__main__":
    main()
