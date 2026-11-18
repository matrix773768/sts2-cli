"""Search bounded Act 2 candidates, then replay each returned plan in a fresh native process."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
from time import perf_counter

from profiles import BUDGETS
from sample import f1, f2, setup

MAX_PLAN = 48


class Session(f2.Session):
    def __enter__(self):
        self.engine = f1.i2.engine_client.EngineClient(
            deadline=self.deadline, log_root=self.output, command_timeout=34)
        return self


class Difference(Exception):
    def __init__(self, phase, expected, actual):
        super().__init__(f"First strict difference at {phase}")
        self.phase = phase
        self.expected = expected
        self.actual = actual


def equal(phase, expected, actual):
    if expected != actual:
        raise Difference(phase, expected, actual)


def frame_hash(frame):
    return f1.digest(json.dumps(frame, sort_keys=True, separators=(",", ":")).encode())


@contextmanager
def restored(output, root):
    path = output / root["checkpoint"]
    original = path.read_bytes()
    if f1.digest(original) != root["checkpoint_sha256"]:
        raise f1.i2.StopRun("root_mismatch", "Source bytes differ from manifest")
    with Session(output, seconds=42) as game:
        state = game.request("load_save", path=str(path), lang="en")
        if state["decision"] != "map_select":
            raise f1.i2.StopRun("root_mismatch", "Checkpoint is not on the map")
        state = game.execute_action(root["entry"])
        if state != root["public_root"] or game.request("f1_begin") != root["identity"]:
            raise f1.i2.StopRun("root_mismatch", "Live or public start differs from sampling")
        try:
            yield game, state
        finally:
            if path.read_bytes() != original:
                raise f1.i2.StopRun("root_mismatch", "Checkpoint mutated")


def search(output, root, budget, fixed_actions=None, *, restore=restored):
    nodes, soft, cancel = budget
    row = dict(node_budget=nodes, soft_ms=soft, cancel_ms=cancel, root_verified=False)
    plan = None
    clock = perf_counter()
    try:
        with restore(output, root) as (game, _):
            row["root_verified"] = True
            before = game.request("f1_audit")
            params = {"fixed_actions": fixed_actions} if fixed_actions else {}
            plan = game.request("i1_capture", node_budget=nodes, **params)
            row["capture_wall_ms"] = game.last_request_ms
            equal("search_source", before, game.request("f1_audit"))
            row.update({k: v for k, v in plan.items() if k not in (
                "type", "actions", "root", "frames", "mode", "schema_version")})
            if "actions" in plan:
                row["plan_action_count"] = len(plan["actions"])
                row["plan_rounds"] = max((a["turn"] for a in plan["actions"]), default=None)
    except Difference as error:
        row.update(status="source_mutation", detail=str(error))
        plan = None
    except (f1.i2.StopRun, RuntimeError, OSError, TimeoutError) as error:
        row.update(status=f1.classify(error), detail=str(error))
        plan = None
    row["elapsed_ms"] = f1.ms(clock)
    return row, plan


def replay_live(game, state, plan, row, send=None):
    """Strictly replay on an already restored root and leave its native run live."""
    if len(plan["actions"]) != len(plan["frames"]) or not 1 <= len(plan["actions"]) <= MAX_PLAN:
        raise f1.i2.StopRun("invalid_prediction_frames", "Expected a complete bounded set of frames")
    send = send or game.request
    row.update(root_verified=True, matched_actions=0, strict_terminal=False, trace=[],
               terminal_contract="Raw F2 comparison; E2 death-only window contract is inapplicable to a predicted win.")
    game.teacher_frames = []
    game.teacher_choices = row["choice_evidence"] = []
    root_frame = game.request("i1_begin")["state"]
    equal("root", plan["root"], root_frame)
    row["root_frame_sha256"] = frame_hash(root_frame)
    try:
        for index, (action, expected) in enumerate(zip(plan["actions"], plan["frames"]), 1):
            row["attempted_step"] = index
            step = send("i1_step", action=action)
            if step["type"] == "i1_rejected":
                raise f1.i2.StopRun("plan_action_rejected", step["reason"])
            state = step["decision"]
            if state["type"] == "error":
                game.engine_error(state)
            last = index == len(plan["actions"])
            audit = dict(step=index, native_action=step["native_action"], native_ms=step["native_ms"],
                         expected_sha256=frame_hash(expected), actual_sha256=frame_hash(step["state"]),
                         terminal=step["terminal"], decision=state["decision"])
            row["trace"].append(audit)
            equal(index, expected, step["state"])
            equal(f"{index}:terminal_callback", last, step["terminal"])
            if not last:
                equal(f"{index}:active_boundary", "combat_play", state["decision"])
            elif state["decision"] not in ("card_reward", "map_select", "game_over"):
                raise Difference(f"{index}:postcombat_boundary", "native postcombat", state["decision"])
            row["matched_actions"] += 1
        row["strict_terminal"] = True
        game.request("i1_release")
    finally:
        if game.engine.proc.poll() is None:
            row["native_final"] = game.request("f1_final")
    row["status"] = f1.outcome(row, state)
    if row["status"] != "win":
        row["detail"] = "Strict predicted route did not reach a confirmed native win"
    row["terminal_public"] = state
    return state


def replay(output, root, plan):
    row = dict(root_verified=False, matched_actions=0, strict_terminal=False, trace=[])
    if len(plan["actions"]) != len(plan["frames"]) or not 1 <= len(plan["actions"]) <= MAX_PLAN:
        return dict(row, status="invalid_prediction_frames")
    clock = perf_counter()
    try:
        with restored(output, root) as (game, state):
            replay_live(game, state, plan, row)
            row["peak_working_set_bytes"] = game.report["peak_working_set_bytes"]
    except Difference as error:
        row.update(status="prediction_mismatch", first_difference=dict(phase=error.phase,
                   expected=error.expected, actual=error.actual))
    except (f1.i2.StopRun, RuntimeError, OSError, TimeoutError) as error:
        row.update(status=f1.classify(error), detail=str(error))
    row["elapsed_ms"] = f1.ms(clock)
    return row


def control_play(game, state, row, mode, forced):
    return f2.play(game, state, row, mode, forced)


def run(output, root, discovery=None):
    row = dict(id=root["id"], attempts=[], teacher="CombatSolver 0.51.5 offline-oracle")
    reference = {}
    plan = None
    remaining = BUDGETS
    if discovery:
        previous, ref = discovery
        row["attempts"] = previous["attempts"]
        if ref:
            row["first_prediction_budget"] = previous["first_prediction_budget"]
            reference["plan_actions"] = ref["plan_actions"]
            prepare, plan = search(output, root, BUDGETS[0], ref["plan_actions"])
            row["fixed_prediction_preparation"] = prepare
            remaining = ()
        else:
            last = row["attempts"][-1]
            remaining = [b for b in BUDGETS if b[0] > last["node_budget"]] if (
                last["status"] in ("budget_exhausted", "no_complete_win")
                or last.get("boundary") in ("NodeLimit", "TimeLimit", "MemoryNoProgress")) else ()
    for budget in remaining:
        attempt, plan = search(output, root, budget)
        row["attempts"].append(attempt)
        print(root["id"], budget[0], attempt["status"], flush=True)
        if plan and plan.get("predicted_win"):
            row["first_prediction_budget"] = budget[0]
            reference["plan_actions"] = plan.get("actions", [])
            break
        if attempt["status"] not in ("budget_exhausted", "no_complete_win"):
            break
    if plan and plan["status"] == "complete_win":
        verified = replay(output, root, plan)
        row["replay"] = {k: v for k, v in verified.items() if k not in ("trace", "first_difference")}
        reference["verification"] = verified
        print(root["id"], "native", verified["status"], verified["matched_actions"], flush=True)
    if row.get("replay", {}).get("status") != "win":
        row["stratum"] = "unresolved"
        return row, reference

    fast = f1.measure(output, root, "B")
    simple = f1.measure(output, root, "A")
    row["controls"] = {"A": fast, "B": simple}
    row["controls"]["A"].update(policy="A", policy_version="M1-F2-discard-v1/Q1+Choice")
    row["controls"]["B"].update(policy="B", policy_version="M1-F2-discard-v1/hand-order")
    outcome = row["replay"]["native_final"]["outcome"]
    row["teacher_hp_loss_ratio"] = outcome["hp_lost"] / outcome["initial_hp"]
    low_loss = fast["status"] == "win" and fast["native_final"]["outcome"]["hp_lost"] <= 0.25 * outcome["initial_hp"]
    row["stratum"] = "control" if low_loss else "research"
    return row, reference


def verify_reference(output, roots, reference_path):
    refs = json.loads(reference_path.read_text(encoding="utf-8"))
    verified = {}
    for root in roots:
        rid = root["id"]
        ref = refs.get(rid, {})
        archived = ref.get("verification", {})
        if archived.get("status") != "win":
            continue
        preparation, plan = search(output, root, BUDGETS[0], ref["plan_actions"])
        if plan is None or preparation["status"] != "complete_win":
            raise ValueError(f"{rid}: reference prediction preparation failed: {preparation}")
        native = replay(output, root, plan)
        equal(f"{rid}:root_digest", archived["root_frame_sha256"], native["root_frame_sha256"])
        equal(f"{rid}:step_digests", [t["actual_sha256"] for t in archived["trace"]],
              [t["actual_sha256"] for t in native["trace"]])
        equal(f"{rid}:outcome", archived["native_final"]["outcome"], native["native_final"]["outcome"])
        equal(f"{rid}:postcombat_resources", archived["native_final"]["resources"], native["native_final"]["resources"])
        equal(f"{rid}:status", "win", native["status"])
        verified[rid] = native
        print(rid, "archived route verified", native["matched_actions"], flush=True)
    if not verified:
        raise ValueError("The reference and manifest share no winning routes")
    f1.write(output / "reference-verification.json", verified)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--reuse-discovery", type=Path, help="Resume the original discovery batch")
    mode.add_argument("--verify-reference", type=Path, help="Verify archived winning actions without searching")
    args = parser.parse_args()
    output = args.output.resolve()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    if (manifest["game_sha256"], manifest["solver_sha256"], manifest["source_sha256"]) != (
            f1.i2.NATIVE_HASH, f1.i2.SOLVER_HASH, f1.digest(f1.BOSS_ROUTE.read_bytes())):
        raise ValueError("Candidate provenance differs from the pinned inputs")
    setup(output)
    f1.Session, f1.play = Session, control_play
    if args.verify_reference:
        verify_reference(output, manifest["roots"], args.verify_reference)
        return
    prior, plans = {}, {}
    if args.reuse_discovery:
        archived = args.reuse_discovery
        if (archived / "manifest.json").read_bytes() != (output / "manifest.json").read_bytes():
            raise ValueError("Discovery batch belongs to different roots")
        prior = {r["id"]: r for r in json.loads((archived / "evaluation.json").read_text(encoding="utf-8"))}
        plans = json.loads((archived / "reference-routes.json").read_text(encoding="utf-8"))
    rows, references = [], {}
    for root in manifest["roots"]:
        rid = root["id"]
        row, ref = run(output, root, (prior[rid], plans.get(rid)) if prior else None)
        rows.append(row)
        if ref:
            references[root["id"]] = ref
        f1.write(output / "evaluation.json", rows)
        f1.write(output / "reference-routes.json", references)


if __name__ == "__main__":
    main()
