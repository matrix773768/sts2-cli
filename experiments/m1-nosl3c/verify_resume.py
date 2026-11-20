"""Kill the pilot during an in-flight update and compare the resumed ledger to cold control."""
import argparse
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from protocol import HERE, read, digest
from nosl3b_store import unpack, tensors
from nosl_experience import save_json


def db(path):
    return sqlite3.connect(path / "training.sqlite")


def seals(path):
    with db(path) as c:
        return dict(models=dict(c.execute("SELECT step, sha FROM snapshots")),
                    roots={(phase, step, root): sha for phase, step, root, sha in c.execute(
                        "SELECT phase,step,root,sha FROM root_hashes")})


def load_rows(path):
    with db(path) as c:
        return {key: digest([{k: r[k] for k in ("root", "behavior", "mode", "replicate", "feedback", "transitions")}
                             for r in unpack(raw)["rows"]])
                for *key_list, raw in c.execute("SELECT phase,step,root,rows FROM roots")
                for key in (tuple(key_list),)}


def interrupt_then_resume(output, config_path, resumable):
    output.mkdir(parents=True, exist_ok=False)
    config = read(config_path)
    reference = output / "control"
    env = {**os.environ, "PYTHONUTF8": "1"}

    def start(run, suffix):
        cmd = [sys.executable, str(HERE / "run.py"), str(run), "--config", str(config_path)]
        with (output / f"{suffix}.log").open("wb") as log:
            return subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)

    with start(resumable, "unfinished") as proc:
        deadline = time.monotonic() + 90
        seen = None
        while proc.poll() is None and time.monotonic() < deadline:
            with db(resumable) as c:
                last = c.execute("SELECT max(step) FROM snapshots").fetchone()[0]
                n = c.execute("SELECT count(*) FROM roots WHERE phase='train' AND step=1").fetchone()[0]
            if last == 1 and 0 < n < config["roots_per_update"]:
                seen = n
                proc.kill()
                proc.wait(timeout=15)
                break
            time.sleep(.025)
        if seen is None:
            if proc.poll() is None:
                proc.kill()
            raise RuntimeError("Failed to interrupt during a partially committed update")

    prior = seals(resumable)
    with start(resumable, "resumed") as proc:
        if proc.wait(timeout=180) != 0:
            raise RuntimeError("Resume process failed. See resumed.log")
    with start(reference, "uninterrupted") as proc:
        if proc.wait(timeout=180) != 0:
            raise RuntimeError("Uninterrupted reference failed. See uninterrupted.log")

    later = seals(resumable)
    for group in prior:
        assert all(later[group][k] == v for k, v in prior[group].items())
    a, b = load_rows(resumable), load_rows(reference)
    assert a == b
    left = tensors((resumable / "checkpoint-latest.pt").read_bytes())
    right = tensors((reference / "checkpoint-latest.pt").read_bytes())
    assert left["model_sha256"] == right["model_sha256"]
    import torch
    assert torch.equal(left["torch_rng"], right["torch_rng"])
    lopt = left["weights"]["mechanism"]["optimizer"]
    ropt = right["weights"]["mechanism"]["optimizer"]
    assert lopt["param_groups"] == ropt["param_groups"] and lopt["state"].keys() == ropt["state"].keys()
    assert all(torch.equal(tensor, ropt["state"][i][name])
               for i, state in lopt["state"].items() for name, tensor in state.items())
    save_json(output / "resume.json", dict(partial_roots_observed=seen, unchanged_root_seals=len(prior["roots"]),
              unchanged_checkpoint_seals=len(prior["models"]), final_update=left["update"],
              root_group_count=len(a), matching_public_and_terminal_data=True, optimizer_exact=True,
              model_sha256=left["model_sha256"]))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("paused_pilot", type=Path)
    p.add_argument("--config", type=Path, default=HERE / "pilot.json")
    args = p.parse_args()
    interrupt_then_resume(args.output.resolve(), args.config.resolve(), args.paused_pilot.resolve())