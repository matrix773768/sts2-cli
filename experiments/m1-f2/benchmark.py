"""Re-evaluate immutable F1 roots in the isolated F2 host."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
from time import monotonic, perf_counter

HERE = Path(__file__).resolve().parent
F1 = HERE.parent / "m1-f1"
spec = importlib.util.spec_from_file_location("f1_benchmark", F1 / "benchmark.py")
f1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f1)

IRON = "ironclad-a0-run_1-f05"
DEFECT = "defect-a10-run_1-f05"
SILENT = "silent-a0-run_2-f02"
CUBEX = "ironclad-a10-run_2-f06"
VERSION = "M1-F2-discard-v1"
DISCARD = {"CARD.SURVIVOR", "CARD.PREPARED"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class Session(f1.Session):
    def request(self, cmd, **args):
        if cmd == "i1_capture" and getattr(self, "fixed_actions", None):
            args["fixed_actions"] = self.fixed_actions
        response = super().request(cmd, **args)
        if cmd == "i1_step" and response.get("choice_evidence"):
            self.teacher_choices.append(dict(step=len(self.teacher_frames),
                                             **response["choice_evidence"]))
        return response


f1_play = f1.play


def play(game, state, result, mode, forced):
    result["policy_version"] = VERSION if mode in ("A", "B") else "offline-oracle-f2"
    if mode == "C":
        game.teacher_choices = result["teacher_choices"] = []
        if result["id"] == CUBEX:
            historical = next(row for row in read(F1 / "results.json")
                              if row["id"] == CUBEX and row["policy"] == "C")
            game.fixed_actions = historical["plan"]["actions"]
        elif result["id"] == SILENT:
            result["native_neutralize"] = game.request("f1_unpatch_neutralize")
        return f1_play(game, state, result, mode, forced)

    audit = result["id"] in (IRON, DEFECT) or result["id"].startswith("silent-")
    start = monotonic()
    for index in range(1, f1.ACTION_LIMIT + 1):
        if state["decision"] != "combat_play":
            return state
        if monotonic() - start >= 20:
            result["status"] = "time_limit"
            return state
        row = dict(step=index, round=state["round"], player_hp=state["player"]["hp"])
        if result["id"] in (IRON, DEFECT):
            row["public"] = state
        result["trace"].append(row)
        params = {"audit": True} if audit else {}
        if mode == "A":
            clock = perf_counter()
            command = f1.combat_action(state)
            row["decision_ms"] = f1.ms(clock)
            chosen = command["args"].get("card_index")
            discard = chosen is not None and state["hand"][chosen]["id"] in DISCARD
            if discard:
                params.update(force=command, hand_order_discard=True)
            else:
                row["action"] = command
                if audit:
                    row["pre_audit"] = game.request("f1_audit")
                state = game.execute_action(command)
                row["execute_wall_ms"] = game.last_request_ms
                if state["decision"] == "card_select":
                    clock = perf_counter()
                    selection, _ = f1.choose_action(state, None)
                    choice = dict(step=index, phase="choice", action=f1.action(selection), decision_ms=f1.ms(clock))
                    result["trace"].append(choice)
                    if "public" in row:
                        choice["public"] = state
                    state = game.execute_action(choice["action"])
                    choice["execute_wall_ms"] = game.last_request_ms
                if audit and state["decision"] == "combat_play":
                    row["post_audit"] = game.request("f1_audit")
                continue
        elif forced and index == forced[0]:
            params["force"] = forced[1]
            row["forced"] = True
        data = game.request("f1_step", step=index, **params)
        row["execute_wall_ms"] = game.last_request_ms
        state = data.pop("decision")
        for key, value in data.items():
            if key == "decision_ms" and mode == "A":
                continue
            if key != "type":
                row[key] = value
        if row.get("choice_failure"):
            result.update(status="unsupported", detail=row["choice_failure"])
            return state
        if state.get("type") == "error":
            game.engine_error(state)
    if state["decision"] == "combat_play":
        result["status"] = "action_limit"
    return state


def freeze(source, output):
    local = read(source / "manifest.json")
    frozen = read(F1 / "manifest.json")
    if (local["game_sha256"], local["solver_sha256"]) != (frozen["game_sha256"], frozen["solver_sha256"]):
        raise ValueError("F1 build identity mismatch")
    if [root["id"] for root in frozen["roots"]] != [root["id"] for root in local["roots"]]:
        raise ValueError("F1 root list mismatch")
    for root, expected in zip(local["roots"], frozen["roots"]):
        for key in ("identity", "context", "entry", "character", "seed", "ascension"):
            if root[key] != expected[key]:
                raise ValueError(f"Frozen F1 mismatch in {root['id']}: {key}")
        if not (source / root["checkpoint"]).is_file() or (
                f1.digest((source / root["checkpoint"]).read_bytes()) != root["checkpoint_sha256"]):
            raise ValueError(f"Local checkpoint does not match manifest: {root['id']}")
        shutil.copyfile(source / root["checkpoint"], output / root["checkpoint"])
    return {root["id"]: root for root in local["roots"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("f1_output", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--only", choices=("choices", "teacher", "all"), default="all")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    roots = freeze(args.f1_output.resolve(), output)
    f1.DLL = f1.ROOT / "logs/m1-f2-build/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll"
    f1.setup(output)
    f1.Session, f1.play = Session, play
    results = []

    def run(root_id, mode, forced=None, label=None):
        row = f1.measure(output, roots[root_id], mode, forced)
        if label:
            row["repeat"] = label
        if not row.get("root_verified"):
            raise RuntimeError(f"Failed root validation: {row}")
        results.append(row)
        f1.write(output / "results.json", results)

    if args.only != "choices":
        for root_id in (CUBEX, SILENT):
            run(root_id, "C")
    if args.only != "teacher":
        silent = [rid for rid in roots if rid.startswith("silent-")]
        for root_id in silent:
            for mode in ("A", "B"):
                run(root_id, mode)
                run(root_id, mode, label="independent")
        if args.only == "all":
            for root_id in roots:
                if root_id not in silent:
                    for mode in ("A", "B"):
                        run(root_id, mode)
            run(IRON, "B", (5, {"action": "play_card", "args": {"card_index": 3, "target_index": 0}}))
            run(DEFECT, "B", (1, {"action": "play_card", "args": {"card_index": 0, "target_index": 0}}))


if __name__ == "__main__":
    main()
