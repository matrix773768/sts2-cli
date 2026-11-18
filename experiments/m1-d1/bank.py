"""Bounded native collection and append-only labeling, isolated from production."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import random
import sys
from threading import Event, Lock
from time import monotonic, perf_counter
from uuid import uuid4

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-f3a"))
from sample import f1, f2, setup
from search_env import _validate_boundary
from branch_memory import MemorySampler

SCHEMA = 1
VERSION = "m1-d1-v1"
POLICIES = {"hand": "A", "q1": "B"}
TERMINAL = {"win", "death"}
ERRORS = (f1.i2.StopRun, f1.UnsupportedDecision, OSError, RuntimeError, ValueError, KeyError,
          TypeError)
ARCHIVE = f1.BOSS_ROUTE
MECHANISMS = {
    "draw": {"POMMEL_STRIKE", "SHRUG_IT_OFF", "OFFERING", "ACROBATICS", "SKIM"},
    "discard": {"SURVIVOR", "PREPARED", "ACROBATICS"},
    "topdeck": {"HEADBUTT"},
    "hp_spend": {"OFFERING", "HELLRAISER", "BLOODLETTING", "INFERNO"},
    "in_combat_scaling": {"RAMPAGE", "DEMON_FORM", "INFLAME", "NOXIOUS_FUMES"},
    "permanent_growth": {"FEED"},
    "energy_or_cost": {"OFFERING", "ENLIGHTENMENT", "LANTERN", "ICE_CREAM"},
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def stamp(obj):
    return f1.digest(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())


def atomic(path, obj):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


@contextmanager
def writer(directory):
    """Release the single-writer lock automatically on process exit."""
    with (directory / ".writer").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def lineage(spec):
    seed = spec["seed"]
    history = stamp([spec["character"].lower(), spec["ascension"], seed])
    # Bucket on seed to co-locate even different characters on that seed.
    bucket = int(stamp(["native-combat-bank-v1", seed])[:8], 16) % 10
    split = ("development" if seed == "run_1" or bucket < 6 else
             "validation" if bucket < 8 else "test")
    return history, split


def status(error):
    kind = f1.classify(error)
    if isinstance(error, TimeoutError) or kind in {"time_limit", "engine_timeout"}:
        return "timeout"
    if kind == "unsupported":
        return kind
    if kind in {"disk_limit", "action_limit", "root_mismatch"}:
        return kind
    return "execution_fault"


def failure(error):
    return dict(status=status(error), error_type=type(error).__name__,
                detail=str(error).split("; last command=")[0][:1500])


def boundaries(game, state):
    world = game.request("get_map", include_start=True)
    _validate_boundary(state, world)
    return world


class Session(f2.Session):
    def __init__(self, bank, deadline, cancelled, memory=None):
        super().__init__(bank / "engine", seconds=0)
        self.deadline = deadline
        self.cancelled = cancelled
        self.rpc_ms = Counter()
        self.on_process = memory.add if memory else None

    def __enter__(self):
        clock = perf_counter()
        self.engine = f1.i2.engine_client.EngineClient(
            deadline=self.deadline, cancelled=self.cancelled.is_set, log_root=self.output,
            command_timeout=12, on_process=self.on_process)
        if self.engine.runtime_version != "9.0.7":
            self.engine.close(graceful=False)
            raise ValueError(f"Expected CoreCLR 9.0.7, got {self.engine.runtime_version}")
        self.startup_ms = elapsed(clock)
        return self

    def request(self, cmd, **args):
        clock = perf_counter()
        try:
            return super().request(cmd, **args)
        finally:
            self.rpc_ms[cmd] += elapsed(clock)


def checkpoint_bytes(bank, root):
    name = root["checkpoint"]
    if Path(name).name != name:
        raise ValueError("Checkpoint must be a local filename")
    path = bank / name
    try:
        source = path.read_bytes()
    except FileNotFoundError as error:
        raise f1.i2.StopRun("root_mismatch", "Checkpoint is missing") from error
    if f1.digest(source) != root["checkpoint_sha256"]:
        raise f1.i2.StopRun("root_mismatch", "Checkpoint SHA-256 mismatch")
    return path, source


def restore_root(game, root, path, enter):
    state = game.request("load_save", path=str(path), lang="en")
    world = boundaries(game, state)
    if (stamp(state), stamp(world)) != (root["map_public_sha256"], root["map_edges_sha256"]):
        raise f1.i2.StopRun("root_mismatch", "Restored map differs from source")
    if not any(root["entry"]["args"] == {k: n[k] for k in ("col", "row")}
               for n in state["choices"]):
        raise f1.i2.StopRun("root_mismatch", "Entry is absent from the restored map")
    if root["entry"]["action"] != "select_map_node":
        raise ValueError("Expected a native map entry")
    state = enter(root["entry"])
    identity = game.request("f1_begin")
    for surface, actual, expected in (("public", state, root["public_root"]),
                                       ("live", identity, root["identity"])):
        if actual != expected:
            raise f1.i2.StopRun("root_mismatch", f"{surface}: {stamp(actual)} != {stamp(expected)}")
    return state


@contextmanager
def restore(bank, root, deadline, cancelled, memory=None):
    path, source = checkpoint_bytes(bank, root)
    with Session(bank, deadline, cancelled, memory) as game:
        try:
            yield game, restore_root(game, root, path, game.execute_action)
        finally:
            if path.read_bytes() != source:
                raise f1.i2.StopRun("root_mismatch", "Source checkpoint changed during audit")


def classify_root(root):
    p = root["public_root"]["player"]
    deck = p["deck"]
    ids = {c["id"].split(".")[-1] for c in deck}
    ids.update(root["identity"]["resources"]["relics"])
    return dict(room=root["context"]["room_type"], enemies=[e.get("id", e["name"])
                for e in root["public_root"]["enemies"]], deck_size=len(deck),
                upgrades=sum(bool(c["upgraded"]) for c in deck), hp=p["hp"],
                potions=root["identity"]["resources"]["potions"],
                mechanisms=sorted(k for k, v in MECHANISMS.items() if v & ids))


def choose(state, spec, rng):
    decision = state["decision"]
    if decision == "map_select":
        nodes = sorted(state["choices"], key=lambda n: (n["col"], n["row"]))
        index = {"west": 0, "east": -1, "middle": len(nodes) // 2}.get(spec["map"])
        node = rng.choice(nodes) if index is None else nodes[index]
        return {"action": "select_map_node", "args": {k: node[k] for k in ("col", "row")}}
    if decision == "treasure":
        return {"action": "proceed"}
    if decision == "card_reward" and state.get("can_skip") and spec["reward"] == "skip":
        return {"action": "skip_card_reward"}
    if decision == "shop" and spec["shop"] == "buy_cheapest":
        cards = [c for c in state["cards"] if c["is_stocked"] and c["cost"] <= state["player"]["gold"]]
        if cards:
            return {"action": "buy_card", "args": {"card_index": min(
                cards, key=lambda c: (c["cost"], c["index"]))["index"]}}
    return f1.action(f1.choose_action(state, rng)[0])


def audit(bank, root, deadline, cancelled, memory=None):
    clock = perf_counter()
    result = dict(kind="native_root_restore", root_id=root["id"],
                  checkpoint_sha256=root["checkpoint_sha256"], status="pass")
    try:
        with restore(bank, root, deadline, cancelled, memory) as (game, _):
            result.update(startup_ms=game.startup_ms, rpc_ms=dict(game.rpc_ms),
                          peak_working_set_bytes=game.report["peak_working_set_bytes"])
    except ERRORS as error:
        result.update(failure(error))
    result["elapsed_ms"] = elapsed(clock)
    return result


def sample(bank, spec, limits, versions, batch_deadline, cancelled, disk_guard, parent, memory,
           resume_battle=None):
    clock = perf_counter()
    deadline = min(monotonic() + limits["run_seconds"], batch_deadline)
    history, split = lineage(spec)
    commands, roots, validations = [], [], []
    run = dict(id=spec["id"], history=history, partition=split, spec=spec, commands=commands,
               status="action_limit", max_act=0, candidates=0,
               offline_teacher_assisted=bool(resume_battle or spec.get("archive") or (
                   parent and parent["run"]["offline_teacher_assisted"])))
    rng = random.Random(spec.get("policy_seed", spec["seed"]))
    candidate_path = None
    timing = Counter()
    try:
        with Session(bank, deadline, cancelled, memory) as game:
            def send(command):
                disk_guard()
                commands.append(command)
                return game.request(**command)

            if parent:
                run["parent"] = dict(run_id=parent["run"]["id"], root_id=parent["root"]["id"],
                                     prefix_length=parent["prefix_length"] - 1)
            if resume_battle:
                path, source = checkpoint_bytes(bank, parent["root"])
                try:
                    state = restore_root(game, parent["root"], path,
                                         lambda entry: send(dict(cmd="action", **entry)))
                    state = resume_battle(game, state, send)
                finally:
                    if path.read_bytes() != source:
                        raise f1.i2.StopRun("root_mismatch", "Source checkpoint changed during continuation")
            elif parent:
                root = parent["root"]
                path = bank / root["checkpoint"]
                if f1.digest(path.read_bytes()) != root["checkpoint_sha256"]:
                    raise f1.i2.StopRun("root_mismatch", "Continuation source hash mismatch")
                state = game.request("load_save", path=str(path), lang="en")
                if (stamp(state), stamp(boundaries(game, state))) != (
                        root["map_public_sha256"], root["map_edges_sha256"]):
                    raise f1.i2.StopRun("root_mismatch", "Continuation map differs")
            elif spec.get("archive"):
                source = ARCHIVE.read_bytes()
                run["archive_sha256"] = f1.digest(source)
                archive = [json.loads(line) for line in source.splitlines()]
                state = None
                for command in archive:
                    if len(commands) >= limits["run_actions"]:
                        raise f1.i2.StopRun("action_limit", "Historical replay exceeds budget")
                    state = send(command)
                if state["decision"] != "card_reward" or state["context"]["room_type"] != "Boss":
                    raise ValueError("Archived replay did not reach the native Boss reward")
                if spec["archive"] == "offering":
                    offering = next((c for c in state["cards"] if c["id"] == "CARD.OFFERING"), None)
                    if offering is None:
                        raise ValueError("Archived Boss reward lacks Offering")
                    state = send(dict(cmd="action", action="select_card_reward",
                                      args={"card_index": offering["index"]}))
                else:
                    state = send(dict(cmd="action", action="skip_card_reward"))
            else:
                state = send(dict(cmd="start_run", character=spec["character"],
                                  ascension=spec["ascension"], seed=spec["seed"], lang="en"))

            combat_steps = 0
            combat_start = monotonic()
            run["startup_ms"] = game.startup_ms
            while True:
                disk_guard()
                decision = state["decision"]
                context = state["context"]
                run["max_act"] = max(run["max_act"], context["act"])
                run["last_context"] = context
                if decision == "game_over":
                    run["status"] = "run_victory" if state["victory"] else "death"
                    break
                if len(commands) >= limits["run_actions"]:
                    break
                if decision == "combat_play":
                    if combat_steps >= limits["combat_actions"]:
                        run["status"] = "combat_action_limit"
                        break
                    if monotonic() - combat_start >= limits["combat_seconds"]:
                        run["status"] = "timeout"
                        break
                    combat_steps += 1
                    step = send(dict(cmd="f1_step", step=combat_steps))
                    for key in ("observe_ms", "decision_ms", "execute_ms"):
                        timing[key] += step[key]
                    timing["f1_step_rpc_ms"] += game.last_request_ms
                    commands[-1]["resolved"] = {k: step[k] for k in ("action", "choice_requests",
                                                                         "choice_checks")}
                    if step.get("choice_failure"):
                        raise f1.i2.StopRun("unsupported", str(step["choice_failure"]))
                    state = step["decision"]
                    if state.get("type") == "error":
                        game.engine_error(state)
                    continue

                entry = choose(state, spec, rng)
                command = dict(cmd="action", **entry)
                if decision != "map_select":
                    state = send(command)
                    continue
                collect = context["act"] >= limits["min_act"]
                map_state = state
                if collect:
                    world = boundaries(game, state)
                    candidate_path = bank / f"d1-{uuid4().hex}.save.json"
                    result = game.request("write_continue_save", path=str(candidate_path))
                    if not result.get("success") or result.get("room_type") != "MapRoom":
                        raise ValueError("Native save requires MapRoom")
                state = send(command)
                if state["decision"] != "combat_play":
                    if candidate_path is not None:
                        candidate_path.unlink()
                        candidate_path = None
                    continue
                combat_steps = 0
                combat_start = monotonic()
                identity = game.request("f1_begin")
                if not collect:
                    continue
                run["candidates"] += 1
                checkpoint_sha = f1.digest(candidate_path.read_bytes())
                rid = stamp([versions["native_identity"], identity["live"]])
                root = dict(id=rid, run_id=run["id"], history=history, partition=split,
                            offline_teacher_assisted=run["offline_teacher_assisted"],
                            character=spec["character"], ascension=spec["ascension"], seed=spec["seed"],
                            context=state["context"], identity=identity, public_root=state,
                            checkpoint=candidate_path.name, checkpoint_sha256=checkpoint_sha,
                            entry=entry, entry_command_index=len(commands), versions=versions,
                            map_public_sha256=stamp(map_state), map_edges_sha256=stamp(world))
                root["classification"] = classify_root(root)
                validation = audit(bank, root, min(deadline, monotonic() + limits["audit_seconds"]), cancelled, memory)
                validation.update(run_id=run["id"], occurrence=len(commands))
                validations.append(validation)
                if validation["status"] == "pass":
                    roots.append(root)
                elif validation["status"] == "root_mismatch":
                    quarantine = bank / "quarantine"
                    quarantine.mkdir(exist_ok=True)
                    candidate_path.replace(quarantine / candidate_path.name)
                    validation["quarantined"] = candidate_path.name
                else:
                    candidate_path.unlink()
                candidate_path = None
                combat_start = monotonic()
                if run["candidates"] >= limits["roots_per_run"]:
                    run["status"] = "sample_cap"
                    break
    except ERRORS as error:
        run.update(failure(error))
    finally:
        if candidate_path is not None:
            candidate_path.unlink(missing_ok=True)
    run.update(elapsed_ms=elapsed(clock), combat_timing_ms=dict(timing))
    run["actions"] = sum(c["cmd"] in {"action", "f1_step"} for c in commands)
    if "game" in locals():
        run.update(rpc_ms=dict(game.rpc_ms), peak_working_set_bytes=game.report["peak_working_set_bytes"])
    return dict(run=run, roots=roots, validations=validations)


def evaluate(bank, root, policy, deadline, cancelled):
    clock = perf_counter()
    result = dict(id=root["id"], root_id=root["id"], policy=policy, policy_version=f2.VERSION,
                  uses_hidden_rng=False, trace=[], resources_before=root["identity"]["resources"])
    try:
        with restore(bank, root, deadline, cancelled) as (game, state):
            result.update(root_verified=True, cold_root_ms=elapsed(clock))
            state = f2.play(game, state, result, POLICIES[policy], None)
            result["native_final"] = game.request("f1_final")
            if "status" not in result:
                result["status"] = f1.outcome(result, state)
            result.update(rpc_ms=dict(game.rpc_ms), startup_ms=game.startup_ms,
                          peak_working_set_bytes=game.report["peak_working_set_bytes"])
    except ERRORS as error:
        result.update(failure(error))
    if result["status"] == "time_limit":
        result["status"] = "timeout"
    final = result.get("native_final", {})
    trace = result.pop("trace")
    actions = [{key: row[key] for key in ("action", "round", "choice_requests", "choice_checks")
                if key in row} for row in trace]
    result.update(action_count=sum("action" in row for row in actions),
                  rounds=final.get("round"), elapsed_ms=elapsed(clock))
    result["timing_ms"] = {
        key: sum(row.get(key, 0) for row in trace)
        for key in ("observe_ms", "decision_ms", "execute_ms", "execute_wall_ms")
    }
    result["action_count"] += sum(len(row.get("choice_requests", [])) for row in trace)
    result["timing_ms"]["instrumented_actions"] = sum("execute_ms" in row for row in trace)
    if final:
        result.update(outcome=final["outcome"], resources_after=final["resources"],
                      resource_delta=resource_delta(result["resources_before"], final["resources"]),
                      terminal_callback=final["terminal_callback"],
                      choice_requests=final["choice_requests"], choice_checks=final["choice_checks"])
        result["timing_ms"].update({k: final[k] for k in ("choice_observation_ms", "choice_decision_ms")})
    return result, actions


def counts(values):
    return dict(sorted(Counter(values).items()))


def resource_delta(before, after):
    result = {k: after[k] - before[k] for k in ("hp", "max_hp", "gold")}
    for key in ("deck", "relics"):
        old, new = Counter(before[key]), Counter(after[key])
        result[key] = dict(added=sorted((new - old).elements()),
                           removed=sorted((old - new).elements()))
    result["potion_slots"] = [dict(slot=i, before=old, after=new)
                             for i, (old, new) in enumerate(zip(before["potions"], after["potions"]))
                             if old != new]
    return result



def isolate_checkpoint(bank, root, validation):
    if validation["status"] != "root_mismatch":
        return
    validation["checkpoint_unavailable"] = True
    file = bank / Path(root["checkpoint"]).name
    if file.exists() and f1.digest(file.read_bytes()) != root["checkpoint_sha256"]:
        quarantine = bank / "quarantine"
        quarantine.mkdir(exist_ok=True)
        file.replace(quarantine / file.name)
        validation["quarantined"] = file.name


def index(manifest):
    roots = manifest["roots"]
    runs = manifest["runs"]
    evaluations = defaultdict(list)
    for row in manifest["evaluations"]:
        evaluations[row["root_id"]].append(row)
    native_routes = {v["route_id"] for v in manifest["validations"]
                     if v["kind"] == "solver_native_replay" and v["status"] == "win"}
    quality = defaultdict(int)
    for route in manifest["routes"]:
        if route["kind"] == "solver_prediction" and route["complete"]:
            quality[route["root_id"]] = max(quality[route["root_id"]], 3 if route["id"] in native_routes else 2)
    native_evaluations = {e["id"] for e in manifest["evaluations"] if
                          e.get("root_verified") and e["status"] in TERMINAL}
    routes = {r.get("id", r.get("evaluation_id")): r for r in manifest["routes"] if r["complete"] and (
        r.get("id") in native_routes or r.get("evaluation_id") in native_evaluations)}
    for evidence in manifest["validations"]:
        if evidence["kind"] != "native_counterfactual" or evidence["status"] != "pass":
            continue
        baseline = routes.get(evidence["baseline_route_id"])
        variant = routes.get(evidence["variant_route_id"])
        root_id = evidence["root_id"]
        if (baseline and variant and evidence["baseline_route_id"] != evidence["variant_route_id"]
                and baseline["root_id"] == variant["root_id"] == root_id
                and baseline.get("comparison_key") == variant.get("comparison_key") == evidence["comparison_key"]
                and evidence["comparison_key"] and evidence["intervention"]
                and baseline["actions"] != variant["actions"]):
            quality[root_id] = 4
    compact = []
    for root in roots:
        labels = evaluations[root["id"]]
        available = not any(v.get("checkpoint_unavailable") and v["root_id"] == root["id"]
                            for v in manifest["validations"])
        compact.append({k: root[k] for k in ("id", "run_id", "history", "partition", "seed",
                       "character", "ascension", "context", "classification", "offline_teacher_assisted",
                       "checkpoint_sha256")} | dict(
            checkpoint_available=available, live=root["identity"]["live"], encounter=root["identity"]["encounter"],
            level=f'L{max(quality[root["id"]], int(any(e["status"] in TERMINAL for e in labels)))}',
            evaluations=[{k: e.get(k) for k in ("id", "policy", "status", "outcome", "action_count",
                                                "rounds", "elapsed_ms")} for e in labels]))
    seconds = sum(b["seconds"] for b in manifest["collection_batches"])
    later = sum(r["context"]["act"] >= 2 for r in roots)
    metrics = dict(roots=len(roots), act2_plus=later, histories=len({r["history"] for r in roots}),
                   act2_plus_histories=len({r["history"] for r in roots if r["context"]["act"] >= 2}),
                   available_roots=sum(r["checkpoint_available"] for r in compact),
                   seeds=len({r["seed"] for r in roots}), attempted_histories=len({r["history"] for r in runs}),
                   partitions=counts(r["partition"] for r in roots),
                   partitions_histories=counts(p for _, p in {(r["history"], r["partition"]) for r in roots}),
                   run_status=counts(r["status"] for r in runs), act2_runs=sum(r["max_act"] >= 2 for r in runs),
                   unassisted_act2_runs=sum(r["max_act"] >= 2 and not r["offline_teacher_assisted"] for r in runs),
                   characters=counts(r["character"] for r in roots),
                   acts=counts(str(r["context"]["act"]) for r in roots),
                   rooms=counts(r["classification"]["room"] for r in roots),
                   encounters=counts(r["identity"]["encounter"] for r in roots),
                   mechanisms=counts(t for r in roots for t in r["classification"]["mechanisms"]),
                   validation_status=counts(v["status"] for v in manifest["validations"] if
                                            v["kind"] == "native_root_restore"),
                   duplicates=sum(o["duplicate"] for o in manifest["occurrences"]),
                   candidates=sum(r["candidates"] for r in runs), seconds=seconds,
                   levels=counts(r["level"] for r in compact),
                   evaluation_status={p: counts(e["status"] for e in manifest["evaluations"] if e["policy"] == p)
                                      for p in POLICIES})
    if seconds:
        for name, amount in dict(strict=len(roots), act2_plus=later, candidates=metrics["candidates"],
                                 terminal_runs=sum(r["status"] in {"death", "run_victory"} for r in runs),
                                 victories=sum(r["status"] == "run_victory" for r in runs)).items():
            metrics[f"{name}_per_minute"] = 60 * amount / seconds
    return dict(schema=SCHEMA, versions=manifest["versions"], metrics=metrics, roots=compact,
                searches=manifest.get("searches", []),
                runs=[{k: v for k, v in r.items() if k not in ("commands", "detail")} for r in runs],
                occurrences=manifest["occurrences"], collection_batches=manifest["collection_batches"],
                validations=[{k: v for k, v in r.items() if k not in ("detail", "quarantined", "evidence")}
                             for r in manifest["validations"]])


def elapsed(clock):
    return (perf_counter() - clock) * 1000


def config_specs(config):
    limits = config["limits"]
    for key in ("run_seconds", "batch_seconds", "audit_seconds", "combat_seconds", "run_actions",
                "combat_actions", "roots_per_run", "max_runs", "disk_mib", "min_act"):
        if type(limits[key]) is not int or limits[key] <= 0:
            raise ValueError(f"Expected positive integer limit {key}")
    if limits["run_actions"] > f1.i2.STEP_LIMIT:
        raise ValueError(f"Run actions exceed the host's {f1.i2.STEP_LIMIT} action limit")
    specs = [config["defaults"] | row for row in config["runs"]]
    if len(specs) > limits["max_runs"] or len({s["id"] for s in specs}) != len(specs):
        raise ValueError("Run count exceeds its budget or IDs repeat")
    available = {}
    for spec in specs:
        if spec["map"] not in {"west", "middle", "east", "random"} or (
            spec["reward"] not in {"first", "skip"} or spec["shop"] not in {"leave", "buy_cheapest"}
        ):
            raise ValueError(f"Unknown policy in {spec['id']}")
        if spec.get("archive") and (spec["archive"] not in {"offering", "skip"} or
                (spec["character"], spec["ascension"], spec["seed"]) != ("Ironclad", 0, "run_1")):
            raise ValueError("The historical archive belongs to Ironclad A0 run_1")
        if "resume" in spec:
            resume = spec["resume"]
            parent = available.get(resume["run"])
            if (spec.get("archive") or not parent or lineage(spec) != lineage(parent)
                    or type(resume["combat"]) is not int or resume["combat"] < 1):
                raise ValueError("Continuation requires an earlier same-history run and a valid combat ordinal")
        available[spec["id"]] = spec
    return specs


def parent_for(spec, manifest):
    if "resume" not in spec:
        return None
    target = spec["resume"]
    run = next((r for r in manifest["runs"] if r["id"] == target["run"]), None)
    if run is None:
        return None
    if (run["history"], run["partition"]) != lineage(spec):
        raise ValueError("Continuation must preserve parent history and partition")
    occurrences = sorted((r for r in manifest["occurrences"] if r["run_id"] == run["id"]),
                         key=lambda r: r["prefix_length"])
    if not 1 <= target["combat"] <= len(occurrences):
        return {"unavailable": True}
    occurrence = occurrences[target["combat"] - 1]
    root = next(r for r in manifest["roots"] if r["id"] == occurrence["root_id"])
    if any(v.get("checkpoint_unavailable") and v["root_id"] == root["id"] for v in manifest["validations"]):
        return {"unavailable": True}
    # A duplicate's canonical save can have a different map prefix.
    if root["run_id"] != run["id"]:
        return {"unavailable": True}
    return {"run": run, "root": root, "prefix_length": occurrence["prefix_length"]}


def collect(bank, manifest, config, args, save, disk_guard):
    specs = config_specs(config)
    limits = config["limits"]
    clock = perf_counter()
    deadline = monotonic() + limits["batch_seconds"]
    cancelled = Event()
    jobs = {}
    batch = dict(workers=args.workers, seconds=0, runs=0)
    done = {r["id"] for r in manifest["runs"]}
    by_id = {r["id"]: r for r in manifest["roots"]}

    def publish(record):
        run = record["run"]
        for root in record["roots"]:
            rid = root["id"]
            duplicate = rid in by_id
            if duplicate and by_id[rid]["history"] != root["history"]:
                # The same state may not be published in another lineage's split.
                record["validations"].append(dict(kind="native_root_restore", root_id=rid,
                    run_id=run["id"], status="cross_history_collision",
                    checkpoint_sha256=root["checkpoint_sha256"]))
                continue
            if not duplicate:
                by_id[rid] = root
                manifest["roots"].append(root)
            manifest["occurrences"].append(dict(root_id=rid, run_id=run["id"], duplicate=duplicate,
                                                  prefix_length=root["entry_command_index"]))
        manifest["validations"].extend(record["validations"])
        manifest["runs"].append(run)
        batch["runs"] += 1
        batch["seconds"] = perf_counter() - clock
        if not any(b is batch for b in manifest["collection_batches"]):
            manifest["collection_batches"].append(batch)
        save()
        for root in record["roots"]:
            if by_id[root["id"]] is not root:
                (bank / root["checkpoint"]).unlink(missing_ok=True)
        done.add(run["id"])
        print(run["id"], run["status"], len(record["roots"]), flush=True)

    with MemorySampler() as memory, ThreadPoolExecutor(max_workers=args.workers) as pool:
        try:
            while monotonic() < deadline:
                pending = [s for s in specs if s["id"] not in done and s["id"] not in jobs]
                for spec in pending:
                    if len(jobs) >= args.workers:
                        break
                    disk_guard()
                    parent = parent_for(spec, manifest)
                    if "resume" in spec and parent is None:
                        continue
                    if parent and parent.get("unavailable"):
                        history, split = lineage(spec)
                        publish(dict(run=dict(id=spec["id"], status="source_unavailable", max_act=0,
                                             candidates=0, history=history, partition=split, spec=spec,
                                             commands=[], offline_teacher_assisted=False),
                                     roots=[], validations=[]))
                        continue
                    jobs[spec["id"]] = pool.submit(sample, bank, spec, limits, manifest["versions"],
                                                   deadline, cancelled, disk_guard, parent, memory)
                if not jobs:
                    break
                # Consume in config order to make duplicate ownership reproducible.
                run_id = next(iter(jobs))
                record = jobs.pop(run_id).result()
                if record["run"]["status"] == "disk_limit" or (
                        monotonic() >= deadline and record["run"]["status"] == "timeout"):
                    # Retry an interrupted run from its configured source.
                    batch["stop_reason"] = ("disk_limit" if record["run"]["status"] == "disk_limit"
                                            else "batch_deadline")
                    break
                publish(record)
        except KeyboardInterrupt:
            batch["stop_reason"] = "interrupt"
        except f1.i2.StopRun as error:
            if error.status != "disk_limit":
                raise
            batch["stop_reason"] = error.status
        finally:
            cancelled.set()
    if not batch["runs"] and batch.get("stop_reason"):
        manifest["collection_batches"].append(batch)
    if batch["runs"] or batch.get("stop_reason"):
        batch.update(seconds=perf_counter() - clock, peak_working_set_bytes=memory.batch_peak,
                     memory_samples=memory.samples)
        save()


def versions_for_host(bank, host):
    setup(bank, host)
    versions = dict(sampler=VERSION, policy=f2.VERSION, game="0.113.1/26660232",
                    game_sha256=f1.i2.NATIVE_HASH, solver_sha256=f1.i2.SOLVER_HASH,
                    solver="0.51.5/78e4545e825e58c3d999354b1ffcd54241b1d2cf",
                    headless_sha256=f1.digest(f1.DLL.read_bytes()), coreclr="9.0.7",
                    native_identity="f1-continuation-v1",
                    archive_sha256=f1.digest(ARCHIVE.read_bytes()))
    versions["native_identity"] = stamp([versions[k] for k in (
        "game", "game_sha256", "solver_sha256", "headless_sha256", "coreclr", "native_identity")])
    return versions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("sample", "evaluate", "audit", "index"))
    parser.add_argument("bank", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--extend", action="store_true", help="Append runs to the pinned configuration")
    parser.add_argument("--workers", type=int, choices=(1, 2, 4), default=1)
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--policy", choices=tuple(POLICIES), action="append")
    parser.add_argument("--repeat", action="store_true")
    parser.add_argument("--host", default="m1-f3b-build")
    args = parser.parse_args()
    bank = args.bank.resolve()
    path = bank / "manifest.json"
    if args.operation == "index":
        print(json.dumps(index(read(path))["metrics"], ensure_ascii=False, indent=2))
        return
    bank.mkdir(parents=True, exist_ok=True)
    with writer(bank):
        config = read(args.config) if args.config else None
        if args.operation == "sample" and config is None:
            parser.error("sample requires --config")
        manifest = read(path) if path.exists() else None
        if config is None:
            if manifest is None:
                parser.error("bank does not exist")
            config = manifest["config"]
        config_specs(config)
        versions = versions_for_host(bank, args.host)
        if manifest is None:
            manifest = dict(schema=SCHEMA, config=config, versions=versions,
                            game_sha256=versions["game_sha256"], solver_sha256=versions["solver_sha256"],
                            **{key: [] for key in ("runs", "roots", "occurrences", "evaluations",
                                                   "routes", "validations", "collection_batches")})
        if (manifest["versions"], manifest["schema"]) != (versions, SCHEMA):
            raise ValueError("Bank schema or pinned binaries differ")
        if manifest["config"] != config:
            old = manifest["config"]
            allowed_limits = old["limits"] | {"max_runs": config["limits"]["max_runs"]}
            if (not args.extend or args.operation != "sample" or old["defaults"] != config["defaults"]
                    or allowed_limits != config["limits"] or old["runs"] != config["runs"][:len(old["runs"])]
                    or len(config["runs"]) <= len(old["runs"])
                    or config["limits"]["max_runs"] < old["limits"]["max_runs"]):
                raise ValueError("Config drift: --extend permits appending runs and raising max_runs")
            manifest["config"] = config
        # Reap uncommitted checkpoints from an interrupted collection.
        known = {r["checkpoint"] for r in manifest["roots"]}
        for file in bank.glob("d1-*.save.json"):
            prefix = file.name.split(".")[0][3:]
            if len(prefix) == 32 and all(c in "0123456789abcdef" for c in prefix) and file.name not in known:
                file.unlink()

        limit = config["limits"]["disk_mib"] * 1024**2

        disk_lock = Lock()
        next_scan = 0.0
        size = 0

        def disk_guard():
            nonlocal next_scan, size
            with disk_lock:
                if monotonic() >= next_scan:
                    size = 0
                    for directory, _, names in os.walk(bank):
                        for name in names:
                            try:
                                size += (Path(directory) / name).stat().st_size
                            except FileNotFoundError:
                                pass
                    next_scan = monotonic() + 0.25
                if size >= limit:
                    raise f1.i2.StopRun("disk_limit", f"Bank uses {size} of {limit} bytes")

        def save():
            atomic(path, manifest)
            atomic(bank / "index.json", index(manifest))

        save()
        if args.operation == "sample":
            collect(bank, manifest, config, args, save, disk_guard)
            return
        roots = [r for r in manifest["roots"] if not args.root or any(
                 r["id"].startswith(prefix) for prefix in args.root)]
        if not roots:
            parser.error("No matching roots")
        cancelled = Event()
        deadline = monotonic() + config["limits"]["batch_seconds"]
        for root in roots:
            if monotonic() >= deadline:
                break
            disk_guard()
            if args.operation == "audit":
                row = audit(bank, root, min(deadline, monotonic() + config["limits"]["audit_seconds"]), cancelled)
                row.update(kind="repeat_root_restore", id=uuid4().hex)
                manifest["validations"].append(row)
                isolate_checkpoint(bank, root, row)
                save()
                print(root["id"][:12], row["status"], flush=True)
                continue
            for policy in args.policy or POLICIES:
                if monotonic() >= deadline:
                    break
                matches = [e for e in manifest["evaluations"] if
                           (e["root_id"], e["policy"]) == (root["id"], policy)]
                if matches and not args.repeat:
                    continue
                row, actions = evaluate(bank, root, policy, min(deadline, monotonic() + 35), cancelled)
                row["id"] = uid = uuid4().hex
                if row["status"] == "root_mismatch":
                    rejected = dict(kind="repeat_root_restore", id=uuid4().hex, root_id=root["id"],
                                    status=row["status"], detail=row.get("detail"))
                    isolate_checkpoint(bank, root, rejected)
                    manifest["validations"].append(rejected)
                if matches:
                    prior = matches[0]
                    route = next(r for r in manifest["routes"] if r.get("evaluation_id") == prior["id"])
                    fields = ("status", "outcome", "action_count", "rounds", "resources_after",
                              "choice_requests", "choice_checks")
                    equal = actions == route["actions"] and all(row.get(k) == prior.get(k) for k in fields)
                    manifest["validations"].append(dict(kind="native_policy_repeat", root_id=root["id"],
                        expected_evaluation_id=prior["id"], evaluation_id=uid,
                        status="pass" if equal and prior["status"] in TERMINAL else "inconclusive" if equal else "mismatch"))
                manifest["evaluations"].append(row)
                manifest["routes"].append(dict(root_id=root["id"], evaluation_id=uid,
                                               kind="native_policy_trace", actions=actions,
                                               complete=row["status"] in TERMINAL))
                save()
                print(root["id"][:12], policy, row["status"], flush=True)


if __name__ == "__main__":
    try:
        main()
    except f1.i2.StopRun as error:
        if error.status != "disk_limit":
            raise
        print(json.dumps(failure(error)), file=sys.stderr)
        sys.exit(2)
