"""Run the preregistered III-A2 curve on the existing v4 trainer."""
import argparse
from hashlib import sha256
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iii-a1"))
import pilot as a1

v4, torch, p0 = a1.v4, a1.torch, a1.p0
save, read, digest = a1.save, a1.read, a1.digest
A1 = Path("logs/nosl3c-iii-a1-02")
A1_HASH = "beb98aefb2ad295b30fbbc5c0be0a8ef2de6dc8ee2420af99155b3c7deb8b428"
UPDATES = (0, 12, 36, 60, 84)
EVAL_ROOT_SEED = 73192202
EVAL_POLICY_SEED = 43192202


def manifests(out):
    train = [[item["spec"] for item in batch] for batch in read(out / "train-manifest/course-roots.json")]
    evaluation, = read(out / "eval-manifest/course-roots.json")
    return train, [item["spec"] for item in evaluation]


def configure():
    p0["verify_main"]()
    os.environ["STS2_DOTNET"] = str(Path("logs/m0-v5/dotnet9/dotnet.exe").resolve())
    os.environ["STS2_DOTNET_VERSION"] = "9.0.7"
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    a1.targets.worker_bind = p0["accept"]["bind"]
    a1.targets.configure()


def freeze(out):
    out.mkdir(parents=True)
    previous = read(A1 / "protocol.json")
    cfg = previous["config"]
    assert cfg["workers"] == 4 and cfg["policy_seed"] == a1.TRAIN_POLICY_SEED
    cfg["stages"][0]["updates"] = 84
    eval_cfg = a1.read_copy(cfg)
    stage = eval_cfg["stages"][0]
    stage["updates"] = 1
    stage["distribution"].update(seed=EVAL_ROOT_SEED, count=48)
    for name, settings in (("train-manifest", cfg), ("eval-manifest", eval_cfg)):
        directory = out / name
        directory.mkdir()
        v4.schedule(directory, a1.solver, settings)
    batches, roots = manifests(out)
    previous_batches, previous_roots = manifests(A1)
    assert batches[:12] == previous_batches
    assert digest(previous_batches) == previous["train_sha256"]
    assert len(batches) == 84 and all(len(batch) == 24 for batch in batches)
    train = [root for batch in batches for root in batch]
    all_seeds = {root["seed"] for root in train + roots}
    assert len(roots) == 48 and len(all_seeds) == 2064
    assert all(root["hp"] == root["max_hp"] == 999 for root in train + roots)
    assert not all_seeds.intersection(root["seed"] for root in previous_roots)
    p0_roots, = read(Path("logs/nosl3c-iii-p0-01/catalog/course-roots.json"))
    assert not all_seeds.intersection(item["spec"]["seed"] for item in p0_roots)
    excluded = {}
    for name in previous["excluded_ledgers"]:
        with a1.readonly(Path("logs") / name / "training.sqlite") as db:
            seeds = {p0["unpack"](raw)["spec"]["seed"] for raw, in
                     db.execute("SELECT rows FROM roots WHERE phase='train'")}
        assert not all_seeds & seeds
        excluded[name] = len(seeds)
    eval_seeds = [int(digest([EVAL_POLICY_SEED, i])[:16], 16) for i in range(48)]
    save(out / "protocol.json", dict(config=cfg, train_sha256=digest(batches), eval_sha256=digest(roots),
                                     a1_prefix_sha256=digest(previous_batches), excluded_ledgers=excluded,
                                     evaluation_policy_seeds=eval_seeds, checkpoints=UPDATES))


def load_step(database, step):
    with a1.readonly(database) as db:
        raw, stamp = db.execute("SELECT payload,sha FROM snapshots WHERE step=?", (step,)).fetchone()
    assert sha256(raw).hexdigest() == stamp
    return p0["tensors"](raw), stamp


def check_prefix(out):
    payload, stamp = load_step(out / "training/training.sqlite", 12)
    save(out / "a1-gate.json", dict(model_sha256=payload["model_sha256"], expected=A1_HASH, snapshot_sha256=stamp))
    assert payload["model_sha256"] == A1_HASH, "A2 update 12 differs from A1"
    previous, previous_stamp = load_step(A1 / "training/training.sqlite", 12)
    assert previous["model_sha256"] == A1_HASH
    print(f"A1 checkpoint gate passed; serialized match={stamp == previous_stamp}", flush=True)


def main(out, mode, through):
    configure()
    if mode == "freeze":
        freeze(out)
        return
    protocol = read(out / "protocol.json")
    batches, roots = manifests(out)
    assert digest(batches) == protocol["train_sha256"] and digest(roots) == protocol["eval_sha256"]
    cfg = protocol["config"]
    seeds = protocol["evaluation_policy_seeds"]
    training = out / "training"
    database = training / "training.sqlite"
    events = []
    suffix = len(list(out.glob(f"{mode}-workers-*.json")))
    with p0["Meter"]() as meter, p0["observe_workers"](meter, events):
        try:
            if mode == "train":
                training.mkdir(exist_ok=True)
                if database.exists():
                    with a1.readonly(database) as db:
                        latest, = db.execute("SELECT max(step) FROM snapshots").fetchone()
                    if latest is not None and latest >= 12:
                        check_prefix(out)
                def gate(step, _payload):
                    if step == 12:
                        check_prefix(out)
                a1.train(training, cfg, batches, meter, events, through=through, on_checkpoint=gate)
                load_step(database, through)
            else:
                check_prefix(out)
                load_step(database, 84)
                for step in UPDATES:
                    state, _ = load_step(database, step)
                    policy = v4.Policy().eval()
                    policy.load_state_dict(state["model"])
                    assert digest(v4.checkpoint_policy(policy)) == state["model_sha256"]
                    for arm in ("sample", "greedy"):
                        directory = out / f"eval-{step:02d}-{arm}"
                        if (directory / "summary.json").exists():
                            continue
                        tick, before = meter.start_phase(), len(events)
                        statuses = a1.evaluate(directory, cfg, roots, seeds, policy, arm)
                        save(directory / "summary.json", dict(statuses=statuses, resources=meter.end_phase(tick),
                                                              host_starts=len(events)-before))
                        print(directory.name, dict(statuses), flush=True)
        finally:
            save(out / f"{mode}-workers-{suffix:02d}.json", events)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "train", "evaluate"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--through", type=int, choices=range(1, 85), default=84)
    args = parser.parse_args()
    main(args.output.resolve(), args.mode, args.through)
