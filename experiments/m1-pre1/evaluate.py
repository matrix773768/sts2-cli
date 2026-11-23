"""Freeze a development root set and evaluate four direct NOSL policies."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from hashlib import sha256
import gzip
import json
import os
from pathlib import Path
import runpy
import sqlite3
import statistics
import sys
from threading import local, Lock
from time import perf_counter
from types import FunctionType, SimpleNamespace

import torch

from features import Encoder, HERE, SOURCE_HASHES
from network import VERSION
from inference import InferenceGroup
from prepare import collate, checksum
from train import load_policy


def bind(output, host):
    os.environ["STS2_DOTNET"] = str(Path("logs/m0-v5/dotnet9/dotnet.exe").resolve())
    os.environ["STS2_DOTNET_VERSION"] = "9.0.7"
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    sys.path.insert(0, str(HERE.parent/"m1-pre0b"))
    runtime = runpy.run_path(str(HERE.parent/"m1-pre0b/run.py"))
    versions = runtime["bind_host"](SimpleNamespace(output=output, host=host))
    return runtime, versions


def freeze(output, host, through, config_path):
    if through < 256:
        raise ValueError("Expected at least 256 development roots")
    output.mkdir()
    runtime, versions = bind(output, host)
    with ExitStack() as stack:
        catalog = runtime["targets"].open_worker(output, stack, versions).request("synthetic_catalog")
    config = json.loads(config_path.read_bytes()) | {"action_cap": 256}
    jobs = [[i, *runtime["root"](catalog, config, i)] for i in range(through)]
    role, = [item for item in catalog["characters"] if item["name"] == "Ironclad"]
    allowed = ({card["id"] for card in role["cards"]} | set(config["generated_allow"])
               | {"FRANTIC_ESCAPE", "INFECTION", "TOXIC", "WITHER", "DISINTEGRATION", "MIND_ROT",
                  "SLOTH", "WASTE_AWAY", "AMNESIA"}) - set(config["exclude"])
    catalog_sha = runtime["digest"](catalog)
    data = dict(config=config, jobs=jobs, versions=versions, allowed=sorted(allowed), catalog=catalog_sha)
    (output/"dev.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


class Decision:
    def __init__(self, obs):
        self.obs, self.actions = obs, obs["actions"]


class Actor:
    def __init__(self, checkpoint):
        self.model, vocab = load_policy(checkpoint)
        self.encoder = Encoder(vocab)
        self.costs = local()
        self.parameter_count = sum(p.numel() for p in self.model.parameters())

    def forward_many(self, requests):
        batch = {key: torch.from_numpy(array) for key, array in collate(
            [feature for feature, in requests]).items()}
        logits = self.model(batch)
        return [row[:len(feature["actions"])] for row,(feature,) in zip(logits,requests,strict=True)]

    def __call__(self, decision, history):
        start = perf_counter()
        memory = history.numpy() if isinstance(history, torch.Tensor) else history
        features = self.encoder.encode(decision.obs, memory)
        encoded = perf_counter()
        execute = getattr(self.costs, "group", None)
        logits = execute(features) if execute else self.forward_many([(features,)])[0]
        self.costs.measure.append((encoded-start, perf_counter()-encoded))
        return logits, logits.new_zeros(()), decision.obs, decision.actions

    def remember(self, history, observation, action):
        memory = history.numpy() if isinstance(history, torch.Tensor) else history
        return self.encoder.update(memory, observation, action)


def teacher(runtime, checkpoint, update):
    with closing(sqlite3.connect(checkpoint.resolve().as_uri()+"?mode=ro", uri=True)) as db:
        raw, expected = db.execute("SELECT payload, sha FROM snapshots WHERE step=?", (update,)).fetchone()
    if sha256(raw).hexdigest() != expected:
        raise ValueError("Invalid teacher snapshot checksum")
    saved = runtime["p0"]["tensors"](raw)
    v4 = runtime["v4"]
    policy = v4.Policy().eval()
    policy.load_state_dict(saved["model"])
    identity = runtime["digest"](v4.checkpoint_policy(policy))
    if identity != SOURCE_HASHES[1]:
        raise ValueError("Expected the frozen v4 A2 update 84 identity")
    return policy, identity


def distribution(rows):
    valid = [row for row in rows if row["complete"]]
    wins = [row for row in valid if row["status"] == "predicted_win"]
    mean = lambda x: statistics.mean(x) if x else None
    return dict(attempts=len(rows), statuses=dict(Counter(row["status"] for row in rows)),
                complete=len(valid), decisions=sum(row["length"] for row in valid),
                win_rate=len(wins)/len(rows), coverage=len(valid)/len(rows),
                initial_minus_final_hp=mean([r["root"]["hp"]-r["terminal"]["hp"] for r in valid]),
                win_hp_loss=mean([r["root"]["hp"]-r["terminal"]["hp"] for r in wins]),
                cumulative_hp_loss=mean([r["cumulative_loss"] for r in valid]),
                terminal_turn=mean([r["terminal"]["turn"] for r in valid]),
                gold=mean([r["terminal"]["gold"] for r in valid]),
                final_hp=mean([r["terminal"]["hp"] for r in valid]),
                terminal_potions=mean([sum(p is not None for p in r["terminal"]["potions"]) for r in valid]))


def verify_partition(plan, corpora):
    dev_seeds = {job[1]["seed"] for job in plan["jobs"]}
    dev_families = {job[3] for job in plan["jobs"]}
    if len(dev_seeds) != len(plan["jobs"]) or len(dev_families) != len(plan["jobs"]):
        raise ValueError("Repeated development root or family")
    dev_composition = {tuple(sorted(card["id"] for card in job[1]["deck"])) for job in plan["jobs"]}
    for path in corpora:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True)) as db:
            for recipe, in db.execute("""
                       SELECT recipe FROM trajectories JOIN private_tasks USING(id) WHERE complete
                       """):
                spec = json.loads(recipe)
                # PRE0B's random family key is the unupgraded deck multiset.
                composition = tuple(sorted(card["id"] for card in spec["deck"]))
                if composition in dev_composition:
                    raise ValueError("Development deck family leaks into corpus")
                if spec["seed"] in dev_seeds:
                    raise ValueError("Development seed leaks into corpus")


def run_arm(output, runtime, plan, policy, model_hash, workers, frozen_sha, arm, groups=0, batch_size=1):
    output.mkdir()
    versions = plan["versions"]
    cfg = plan["config"]
    allowed = set(plan["allowed"])
    collect = runtime["collect"]
    def measure_group(requests):
        from batched import forward
        decisions, histories = zip(*requests)
        logits, values, state, actions, _ = forward(policy, decisions, torch.stack(histories))
        return [(logits[i, :len(d.actions)], values[i], state[i], actions[i, :len(d.actions)])
                for i,d in enumerate(decisions)]

    if isinstance(policy, Actor):
        old = collect.__wrapped__
        base = SimpleNamespace(WIDTH=(3, 24))
        target = SimpleNamespace(base=base, project=runtime["targets"].project, Decision=Decision)
        collect = torch.inference_mode()(FunctionType(old.__code__, old.__globals__ | {"targets":target}))
    else:
        original = policy.forward
        costs = local()

        def measured(decision, history):
            tick = perf_counter()
            group = getattr(costs, 'group', None)
            result = group(decision, history) if group else original(decision, history)
            costs.measure.append((0.,perf_counter()-tick))
            return result

        policy.forward = measured
    timings = policy.costs if isinstance(policy, Actor) else costs
    thread = local()
    lock = Lock()
    lanes, durations = [], []
    begin = perf_counter()
    with runtime["p0"]["Meter"]() as meter, ExitStack() as services:
        execute = policy.forward_many if isinstance(policy, Actor) else measure_group
        execution_groups = [services.enter_context(InferenceGroup(execute,batch_size,.0001))
                            for _ in range(groups)]
        phase = meter.start_phase()

        def one(job):
            if not hasattr(thread, "lane"):
                thread.lane = runtime["Lane"](output, versions, meter, 96, 512*2**20)
                with lock:
                    if execution_groups:
                        timings.group = execution_groups[len(lanes)%groups]
                    lanes.append(thread.lane)
            ordinal, spec, split, family, room = job
            timings.measure = []
            task = runtime["digest"]([frozen_sha, arm, ordinal])
            row, cost = collect(versions, policy, policy, model_hash, cfg, allowed,
                                 (task, ordinal, spec, split, family, room), thread.lane, True)
            row["behavior"]["model"] = VERSION if isinstance(policy, Actor) else runtime["v4"].MODEL
            return row, cost, timings.measure

        rows = []
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool, gzip.open(output/"public.jsonl.gz","wt",encoding="utf-8") as stream:
                for row, cost, measured in pool.map(one, plan["jobs"]):
                    stream.write(json.dumps(row, separators=(",",":"), allow_nan=False)+"\n")
                    durations.extend(measured)
                    rows.append({key: value for key,value in row.items() if key not in ("steps",)})
        finally:
            for lane in lanes:
                lane.close("development_end")
        resources = meter.end_phase(phase)
    seconds = perf_counter()-begin
    detail = distribution(rows)
    percentile = lambda values: [statistics.median(values)*1000,
                                 statistics.quantiles(values,n=100,method="inclusive")[94]*1000]
    for field, index in (("features_ms_p50_p95",0),("forward_ms_p50_p95",1)):
        detail[field] = percentile([d[index] for d in durations])
    group_times = [item for group in execution_groups for item in group.measures]
    detail.update(seconds=seconds, root_manifest_sha256=frozen_sha, complete_s=detail["complete"]/seconds,
                  decisions_s=detail["decisions"]/seconds, resources=resources,
                  workers=workers, processes=sum(len(lane.events) for lane in lanes),
                  batch_limit=batch_size, inference_groups=groups,
                  actual_batch_mean=statistics.mean(n for n,_ in group_times) if group_times else None,
                  batch_forward_ms_p50_p95=percentile([d for _,d in group_times]) if group_times else None,
                  parameters=sum(p.numel() for p in (policy.model if isinstance(policy, Actor) else policy).parameters()),
                  parameter_bytes=sum(p.numel()*p.element_size()
                                      for p in (policy.model if isinstance(policy, Actor) else policy).parameters()),
                  model_sha256=model_hash, decision_mode="sample", evidence="prediction_only",
                  by_room={room: distribution([r for r in rows if r["room"]==room])
                           for room in sorted({r["room"] for r in rows})},
                  by_hp={hp: distribution([r for r in rows if r["root"]["hp"]==hp])
                         for hp in sorted({r["root"]["hp"] for r in rows})})
    (output/"summary.json").write_text(json.dumps(detail,indent=2),encoding="utf-8")
    return detail


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--count", type=int, default=256)
    parser.add_argument("--roots-config", type=Path, default=HERE/"dev-roots.json")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--teacher", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--behavior", type=Path)
    parser.add_argument("--transfer", type=Path)
    parser.add_argument("--additional-grouped", action="store_true")
    parser.add_argument("--groups", type=int, default=0)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--rollout-model", type=Path)
    parser.add_argument("--corpus", type=Path, nargs="+", default=[])
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.workers < 1 or not 0 <= args.groups <= args.workers or args.batch < 1:
        raise ValueError("Invalid inference pool configuration")
    if args.freeze:
        freeze(args.output, args.host, args.count, args.roots_config)
    else:
        if (args.output.parent/"STOP").exists():
            raise SystemExit("Evaluation paused by campaign STOP")
        args.output.mkdir(exist_ok=True)
        plan = json.loads(args.manifest.read_bytes())
        results = {}
        arms = {"initial":args.weights/"initial.pt", "mechanism":args.weights/"mechanism.pt",
                "joint":args.weights/"final.pt", "behavior":args.behavior, "transfer":args.transfer,
                "a2":None} if not args.rollout_model else {"rollout":args.rollout_model}
        if args.additional_grouped:
            arms["grouped_joint"] = args.weights/"final.pt"
        missing = [name for name,path in arms.items() if name != "a2" and (path is None or not path.is_file())]
        if missing:
            raise FileNotFoundError(f"Evaluation policies missing: {', '.join(missing)}")
        verify_partition(plan, args.corpus)
        runtime, versions = bind(args.output, args.host)
        if versions != plan["versions"]:
            raise ValueError("Development host identity differs")
        frozen_sha = checksum(args.manifest)
        for arm,path in arms.items():
            if arm == "a2":
                policy, model_hash = teacher(runtime,args.teacher,84)
            else:
                policy, model_hash = Actor(path), checksum(path)
            groups = (args.groups or min(2,args.workers)) if arm == "grouped_joint" else (
                0 if args.additional_grouped else args.groups)
            batch_size = args.batch if groups else 1
            retry = 0
            destination = args.output/arm
            while destination.exists() and not (destination/"summary.json").exists():
                retry += 1
                destination = args.output/f"{arm}-{retry}"
            if destination.exists():
                metrics = json.loads((destination/"summary.json").read_bytes())
                if (metrics["model_sha256"], metrics["root_manifest_sha256"], metrics["workers"],
                    metrics["inference_groups"], metrics["batch_limit"]) != (
                        model_hash, frozen_sha, args.workers, groups, batch_size):
                    raise ValueError("Existing development result identity changed")
                results[arm] = metrics
            else:
                results[arm] = run_arm(destination, runtime, plan, policy, model_hash,
                                       args.workers,frozen_sha,arm,groups,batch_size)
            results[arm]["trajectories"] = str(destination/"public.jsonl.gz")
            if path:
                results[arm]["weight_bytes"] = path.stat().st_size
            print(arm, results[arm]["statuses"], results[arm]["complete_s"], flush=True)
        (args.output/"summary.json").write_text(json.dumps(results, indent=2),encoding="utf-8")
