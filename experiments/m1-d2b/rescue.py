"""Attempt one F3B rescue of a recorded natural Q1 death, then continue natively."""
import argparse
import importlib.util
from pathlib import Path
import sys
from threading import Event
from time import monotonic, perf_counter
from uuid import uuid4

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-d1"))
import bank

spec = importlib.util.spec_from_file_location("d2b_f3b", HERE.parent / "m1-f3b/benchmark.py")
f3b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f3b)
f3a = f3b.f3a
ARM = "C"
VERSION = "M1-F3B-v1"
POSTCOMBAT = {"card_reward", "map_select", "game_over"}


def terminal_root(manifest, name):
    run = next((r for r in manifest["runs"] if r["id"] == name), None)
    if run is None or run["status"] != "death":
        raise ValueError("Expected a recorded natural run ending in native death")
    if run["offline_teacher_assisted"] or run.get("parent"):
        raise ValueError("Expected a natural, unbranched source")
    if run["spec"]["map"] == "random":
        raise ValueError("This continuation requires a deterministic map policy")
    roots = [r for r in manifest["roots"] if r["run_id"] == name]
    if not roots:
        raise ValueError("No strictly restored combat root for the run")
    root = max(roots, key=lambda r: r["entry_command_index"])
    for key in ("act", "floor", "room_type"):
        if root["context"][key] != run["last_context"][key]:
            raise ValueError("The recorded death is outside the sampled root")
    if (root["history"], root["partition"]) != bank.lineage(run["spec"]) or (
            run["history"], run["partition"]) != (root["history"], root["partition"]):
        raise ValueError("Root and natural history disagree")
    if root["versions"] != manifest["versions"]:
        raise ValueError("Root does not use the source bank's pinned versions")
    audit = next((v for v in manifest["validations"] if
                  v["root_id"] == root["id"] and v["kind"] == "native_root_restore"
                  and v["status"] == "pass" and v["checkpoint_sha256"] == root["checkpoint_sha256"]), None)
    if not audit or any(v["root_id"] == root["id"] and v.get("checkpoint_unavailable")
                        for v in manifest["validations"]):
        raise ValueError("The source checkpoint needs a passing strict recovery audit")
    index = root["entry_command_index"]
    if run["commands"][index - 1] != dict(cmd="action", **root["entry"]):
        raise ValueError("Run provenance differs from the recorded map entry")
    suffix = run["commands"][index:]
    if not suffix or any(c["cmd"] != "f1_step" or "resolved" not in c for c in suffix):
        raise ValueError("Expected a recorded Q1 combat suffix")
    return run, root, audit, suffix


def same_failure(evaluation, native_actions, suffix):
    return (evaluation["status"] == "death" and evaluation.get("root_verified")
            and evaluation["outcome"]["final_hp"] == 0
            and [{k: v for k, v in row.items() if k != "round"} for row in native_actions]
            == [command["resolved"] for command in suffix])


def discover(output, root, cap, record):
    for potions in (False, True):
        start = perf_counter()
        try:
            search = f3b.search(output, root, ARM, potions, cap, [])
        except (AssertionError, f3a.Difference, *bank.ERRORS) as error:
            search = bank.failure(error) | {"transitions": None}
            if str(error).startswith("PredictionUnsupportedException:"):
                search["status"] = "unsupported"
        used = search["transitions"]
        attempt = dict(potions=potions, cap=cap, status=search["status"], search_status=search["status"],
                       transitions=used, charged_transitions=cap if used is None else used,
                       search_ms=bank.elapsed(start),
                       search_hot_ms=search.get("hot_ms"), search_cpu_ms=search.get("cpu_ms"))
        record["attempts"].append(attempt)
        evidence = output / ("allow.json.gz" if potions else "dry.json.gz")
        f3b.save_history(evidence, search)
        attempt["search_evidence"] = evidence.name
        if search["status"] != "predicted_win":
            continue
        prep, plan = f3b.prepare_native(output, root, search)
        attempt["preparation"] = prep
        if plan is None:
            attempt["status"] = prep["status"]
            continue
        verified = f3a.replay(output, root, plan)
        attempt["verification"] = {k: verified.get(k) for k in
                                    ("status", "elapsed_ms", "matched_actions", "strict_terminal",
                                     "first_difference", "detail")}
        attempt["status"] = verified["status"]
        rid = uuid4().hex
        record["routes"].append(dict(id=rid, root_id=root["id"], kind="solver_prediction",
            complete=True, search_id=record["id"], policy_version=VERSION, uses_hidden_rng=True,
            arm=ARM, potions=potions, transition_budget=cap, transitions=used,
            actions=plan["actions"], stamps=search["stamps"]))
        record["validations"].append(dict(id=uuid4().hex, kind="solver_native_replay", root_id=root["id"],
            route_id=rid, status=verified["status"], matched_actions=verified["matched_actions"],
            strict_terminal=verified["strict_terminal"]))
        if verified["status"] == "win" and verified["strict_terminal"]:
            record["verified"] = verified
            record["route_id"] = rid
            return plan
    return None


def outcome_evidence(row):
    final = row["native_final"]
    return dict(terminal_public=row["terminal_public"], root_frame_sha256=row["root_frame_sha256"],
                choice_evidence=row["choice_evidence"],
                trace=[{k: v for k, v in step.items() if k != "native_ms"} for step in row["trace"]],
                final={k: final[k] for k in ("terminal_callback", "outcome", "round", "resources")})


def apply_and_continue(output, source, run, root, plan, record, limits):
    parent = dict(run=run, root=root, prefix_length=root["entry_command_index"])
    applied = record["applied"] = {}
    branch_spec = run["spec"] | {"id": run["id"] + "-f3b"}
    limits = limits | {"roots_per_run": min(limits["roots_per_run"], 2)}
    continuation_started = None

    def disk_guard():
        size = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
        if size >= limits["disk_mib"] * 1024**2:
            raise bank.f1.i2.StopRun("disk_limit", "D2B continuation disk limit reached")

    def replay(game, state, send):
        nonlocal continuation_started
        start = perf_counter()
        try:
            state = f3a.replay_live(game, state, plan, applied,
                                     lambda cmd, **fields: send(dict(cmd=cmd, **fields)))
            if applied["status"] != "win" or state["decision"] not in POSTCOMBAT:
                raise bank.f1.i2.StopRun("continuation_rejected", "Rewalk did not reach a native win boundary")
            f3a.equal("verified_native_rewalk", outcome_evidence(record["verified"]), outcome_evidence(applied))
        except f3a.Difference as error:
            applied.update(status="prediction_mismatch", first_difference=error.phase)
            raise bank.f1.i2.StopRun("continuation_rejected", str(error)) from error
        except bank.ERRORS as error:
            applied.update(bank.failure(error))
            raise
        finally:
            applied["elapsed_ms"] = bank.elapsed(start)
        applied["resources_delta"] = bank.resource_delta(root["identity"]["resources"],
                                                         applied["native_final"]["resources"])
        applied["matches_verified"] = True
        continuation_started = perf_counter()
        return state

    start = perf_counter()
    branch = bank.sample(output, branch_spec, limits, source["versions"],
                         monotonic() + limits["run_seconds"], Event(), disk_guard, parent, None, replay)
    record["apply_and_continue_ms"] = bank.elapsed(start)
    if continuation_started is not None:
        record["continuation_ms"] = bank.elapsed(continuation_started)
        record["followup_commands"] = len(branch["run"]["commands"]) - 1 - len(plan["actions"])
    branch["run"]["rescue_id"] = record["id"]
    branch["run"]["route_id"] = record["route_id"]
    record["branch_run"] = branch["run"]
    return branch


def publish(output, original, run, root, audit, evaluation, actions, record, branch):
    run_config = original["config"] | {"runs": [run["spec"]]}
    uid = record["id"] + "-q1"
    evaluation["id"] = uid
    manifest = {key: original[key] for key in ("schema", "versions", "game_sha256", "solver_sha256")}
    manifest.update(config=run_config, roots=[root], runs=[run],
        occurrences=[dict(root_id=root["id"], run_id=run["id"], duplicate=False,
                          prefix_length=root["entry_command_index"])],
        evaluations=[evaluation], collection_batches=[], validations=[audit, *record["validations"]],
        routes=[dict(root_id=root["id"], evaluation_id=uid, kind="native_policy_trace",
                     actions=actions, complete=evaluation["status"] in bank.TERMINAL), *record["routes"]],
        rescues=[{k: v for k, v in record.items() if k not in ("routes", "validations", "branch_run",
                                                             "verified", "applied")}])
    if branch:
        manifest["runs"].append(branch["run"])
        manifest["validations"].extend(branch["validations"])
        seen = {root["id"]}
        for r in branch["roots"]:
            duplicate = r["id"] in seen
            if duplicate:
                (output / r["checkpoint"]).unlink()
            else:
                seen.add(r["id"])
                manifest["roots"].append(r)
            manifest["occurrences"].append(dict(root_id=r["id"], run_id=r["run_id"], duplicate=duplicate,
                                                 prefix_length=r["entry_command_index"]))
    bank.atomic(output / "manifest.json", manifest)
    bank.atomic(output / "index.json", bank.index(manifest))
    bank.atomic(output / "rescue.json", record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("run")
    parser.add_argument("output", type=Path)
    parser.add_argument("--host", default="m1-f3b-build")
    parser.add_argument("--cap", type=int, choices=f3b.TIERS, default=128, help="Per potion condition")
    args = parser.parse_args()
    sys.addaudithook(f3b.deny_reference_open)
    source, output = args.source.resolve(), args.output.resolve()
    if source == output or source in output.parents:
        parser.error("Use a new output directory outside the source bank")
    manifest_path = source / "manifest.json"
    source_manifest = manifest_path.read_bytes()
    manifest = bank.read(manifest_path)
    run, root, audit, suffix = terminal_root(manifest, args.run)
    path, payload = bank.checkpoint_bytes(source, root)
    output.mkdir(parents=True)
    if bank.versions_for_host(output, args.host) != manifest["versions"] or bank.f1 is not f3b.f1:
        raise ValueError("F3B host must exactly match the source bank's pinned versions")
    (output / root["checkpoint"]).write_bytes(payload)
    start = perf_counter()
    record = dict(id=uuid4().hex, root_id=root["id"], parent_history=run["history"], parent_run=run["id"],
                  partition=run["partition"], offline_teacher_assisted=True,
                  checkpoint_sha256=root["checkpoint_sha256"], source_manifest_sha256=bank.f1.digest(source_manifest),
                  divergence_at_entry=root["entry_command_index"], policy_version=VERSION, arm=ARM,
                  uses_hidden_rng=True, cap_per_condition=args.cap, attempts=[], routes=[], validations=[])
    branch = None
    evaluation, actions = bank.evaluate(output, root, "q1", monotonic() + 35, Event())
    record["q1_status"] = evaluation["status"]
    record["q1_ms"] = evaluation["elapsed_ms"]
    record["q1_matches_original"] = same_failure(evaluation, actions, suffix)
    record["status"] = "q1_gate_rejected"
    record["origin_result"] = run["status"]
    if record["q1_matches_original"]:
        plan = discover(output, root, args.cap, record)
        record["status"] = "no_verified_win"
        if plan:
            branch = apply_and_continue(output, manifest, run, root, plan, record, manifest["config"]["limits"])
            if record["applied"].get("matches_verified"):
                record["status"] = ("native_continuation" if record["followup_commands"]
                                    else "native_rewalk_only")
                seen = {r["identity"]["live"] for r in manifest["roots"]}
                record["new_strict_roots"] = []
                for candidate in branch["roots"]:
                    live = candidate["identity"]["live"]
                    if live not in seen:
                        seen.add(live)
                        record["new_strict_roots"].append(candidate["id"])
            else:
                record["status"] = "rewalk_rejected"
    record["known_transitions"] = sum(a["transitions"] or 0 for a in record["attempts"])
    record["charged_transitions"] = sum(a["charged_transitions"] for a in record["attempts"])
    record["wall_ms"] = bank.elapsed(start)
    if path.read_bytes() != payload or manifest_path.read_bytes() != source_manifest:
        raise ValueError("Source checkpoint or manifest changed")
    publish(output, manifest, run, root, audit, evaluation, actions, record, branch)
    print(args.run, record["status"], record["known_transitions"], flush=True)


if __name__ == "__main__":
    main()
