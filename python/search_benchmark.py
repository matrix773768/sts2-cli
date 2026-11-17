"""Run fixed first-room search branches and emit JSONL samples plus a JSON summary."""
import argparse
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import platform
from statistics import median
import time

from branch_memory import MemorySampler
from branch_scheduler import BranchTask, run_batch
from room_policy import action, combat_action
from search_env import SearchEnv


SEED = "m0-a-save-load-1"
STOP = ("card_reward", "map_select")


def _neow(state):
    decision = state["decision"]
    if decision == "event_choice":
        option = next(o for o in state["options"] if not o.get("is_locked"))
        return action("choose_option", option_index=option["index"])
    if decision == "card_reward":
        return action("skip_card_reward")
    if decision == "bundle_select":
        return action("select_bundle", bundle_index=0)
    if decision == "card_select":
        return (action("skip_select") if not state["min_select"]
                else action("select_cards", indices="0"))
    raise ValueError(f"Unsupported Neow decision: {decision}")


def make_workload(config, deadline):
    """Prepare two fixed scripts and exact serial references outside timed batches."""
    initialization = {}
    with SearchEnv(**config, deadline=deadline, timings=initialization) as env:
        state = env.reset(seed=SEED)
        for _ in range(20):
            if state["decision"] == "map_select":
                break
            state = env.step(_neow(state))
        checkpoint = env.save_checkpoint()
    choices = [node for node in state["choices"] if node["type"] == "Monster"]
    if len(choices) < 2:
        raise ValueError("Expected two Monster branches from the fixture seed")
    references = []
    for choice in choices[:2]:
        with SearchEnv(**config, deadline=deadline) as env:
            env.reset(checkpoint=checkpoint)
            state = env.step(action("select_map_node", col=choice["col"], row=choice["row"]))
            if state["decision"] != "combat_play":
                raise ValueError("Expected Monster combat")
            for _ in range(299):
                if state["decision"] != "combat_play":
                    break
                state = env.step(combat_action(state))
            if (state["decision"] not in (*STOP, "game_over") or
                    len(env.position().prefix) < 3 or state.get("from_event")):
                raise ValueError(f"Unexpected end of fixed combat: {state['decision']}")
            references.append(env.position())
    return checkpoint, references, initialization


def _stats(values):
    ordered = sorted(values)
    if not ordered:
        return None
    return {"n": len(ordered), "p50": median(ordered),
            "p95": ordered[math.ceil(0.95 * len(ordered)) - 1]}


def run(output, *, game_build, samples, budget, concurrency=(1, 2, 4)):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    config = dict(game_build=game_build, checkpoint_dir=output / "checkpoints", log_root=output / "engines")
    deadline = time.monotonic() + budget
    checkpoint, references, initialization = make_workload(config, deadline)
    original = checkpoint.path.read_bytes()
    summary = {
        "environment": {"os": platform.platform(), "python": platform.python_version(),
                        "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
                        "runtime": checkpoint.runtime_version, "protocol": checkpoint.protocol_version},
        "build": asdict(checkpoint.build), "checkpoint_sha256": checkpoint.sha256,
        "workload": {"seed": SEED, "character": "Ironclad", "ascension": 0,
                     "scripts": [[json.loads(s.action) for s in p.prefix] for p in references]},
        "initialization_seconds": initialization, "requested_samples_per_batch": samples,
        "batch_budget_seconds": budget, "batches": [],
        "limits": ["Fresh processes; OS caches uncontrolled.",
                   "P95 uses nearest rank and is exploratory for small samples.",
                   "Memory is engine working set/RSS only; batch totals are sampled, not summed individual peaks.",
                   "IPC stages include Python transport and engine JSON work.",
                   "Replications use one checkpoint, not independent random games."],
    }
    baseline = None
    with (output / "samples.jsonl").open("w", encoding="utf-8") as raw:
        for workers in concurrency:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            tasks = [BranchTask(checkpoint, actions=tuple(json.loads(s.action) for s in references[i % 2].prefix),
                                task_id=f"{workers}-{i}") for i in range(samples)]
            start = time.monotonic()
            with MemorySampler() as memory:
                results = run_batch(tasks, **config, max_workers=workers, timeout=remaining,
                                    on_process=memory.add)
            elapsed = time.monotonic() - start
            rows = []
            for i, result in enumerate(results):
                match = result.position == references[i % 2] if result.successful else None
                status = "mismatch" if match is False else result.status
                sample = dict(task_id=result.task_id, concurrency=workers, script=i % 2,
                              attempted=result.attempted, status=status, correct=match,
                              decision=(result.observation or {}).get("decision"), victory=result.victory,
                              pid=result.pid, returncode=result.returncode, log_dir=result.log_dir,
                              actions=result.actions, elapsed=result.elapsed, timings=result.timings,
                              peak_bytes=memory.process_peaks.get(result.log_dir), error=result.error)
                raw.write(json.dumps(sample) + "\n")
                rows.append(sample)
            raw.flush()
            valid = [row for row in rows if row["correct"] is True]
            throughput = len(valid) / elapsed
            if workers == 1:
                baseline = throughput
            stages = sorted({key for row in valid for key in row["timings"]})
            statuses = Counter(row["status"] for row in rows)
            truncated = sum(statuses[key] for key in ("action_budget", "timeout", "batch_deadline", "canceled"))
            source_unchanged = checkpoint.path.read_bytes() == original and sha256(original).hexdigest() == checkpoint.sha256
            reaped = all(row["pid"] is None or row["returncode"] is not None for row in rows)
            summary["batches"].append(dict(
                concurrency=workers, attempted=sum(row["attempted"] for row in rows),
                success=len(valid), failure=len(rows) - len(valid) - truncated,
                truncated=truncated, statuses=dict(statuses), wall_seconds=elapsed, throughput=throughput,
                speedup=throughput / baseline if baseline else None,
                end_to_end_seconds=_stats([row["elapsed"] for row in valid]),
                stage_seconds={key: _stats([row["timings"][key] for row in valid if key in row["timings"]])
                               for key in stages},
                engine_peak_bytes=_stats([row["peak_bytes"] for row in rows if row["peak_bytes"] is not None]),
                batch_peak_bytes=memory.batch_peak, memory_samples=memory.samples,
                memory_interval_seconds=memory.interval, source_unchanged=source_unchanged,
                all_processes_reaped=reaped, compared=len(valid), mismatches=statuses["mismatch"],
            ))
            if not source_unchanged or not reaped or statuses["mismatch"]:
                break
    summary["complete"] = (len(summary["batches"]) == len(concurrency)
                           and all(batch["success"] == samples and batch["source_unchanged"]
                                   and batch["all_processes_reaped"] for batch in summary["batches"]))
    summary["unmeasured_concurrency"] = list(concurrency[len(summary["batches"]):])
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--game-build", required=True)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--budget", type=float, default=360)
    args = parser.parse_args()
    if not 1 <= args.samples <= 12 or not math.isfinite(args.budget) or not 0 < args.budget <= 360:
        parser.error("Use 1–12 samples per concurrency and a positive budget up to 360 seconds")
    summary = run(args.output, game_build=args.game_build, samples=args.samples, budget=args.budget)
    for batch in summary["batches"]:
        print(f"{batch['concurrency']}: {batch['success']}/{args.samples}, {batch['throughput']:.3f}/s")
    return 0 if summary["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
