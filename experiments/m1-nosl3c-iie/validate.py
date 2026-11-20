"""Check objective edge cases and scalar/microbatch replay on a real ledger."""
import argparse
from contextlib import closing
from copy import deepcopy
import gzip
import io
import json
from pathlib import Path
import sqlite3

import torch

from objective import Objective
from training import Policy, optimize
from terminal_contract import targets
from nosl_experience import save_json


def objective_checks():
    f = Objective("mixed", 10, .05, 100, 50, .2)
    assert f.loss(0) == 0
    assert all(f.loss(x) < f.loss(x+1) for x in range(999))
    assert Objective("log", 1e-320, 0, 1, 1, 0).loss(999) > 0
    derivative = (f.loss(20.0001)-f.loss(19.9999))/.0002
    assert abs(derivative - (10/30 + .05)) < 1e-8
    win = dict(eligible=True, status="predicted_win", observation={"hp": 220, "turn": 3})
    assert f.reward(win, 200) == 100-.2*3
    death = win | dict(status="death", observation={"hp":0,"turn":3})
    assert f.reward(death, 200) < 0
    assert f.reward(death | {"eligible":False},200) is None
    deltas = [0, 20, 4, 15]
    assert abs(sum(f.loss(x)-f.loss(y) for x,y in zip(deltas,deltas[1:])) + f.loss(15)) < 1e-12


def numeric(ledger, config):
    with closing(sqlite3.connect(ledger / "training.sqlite")) as db:
        raw = db.execute("SELECT payload FROM snapshots WHERE step=0").fetchone()[0]
        initial = torch.load(io.BytesIO(raw), weights_only=True)
        rows = [r for raw, in db.execute("SELECT rows FROM roots WHERE step=0 ORDER BY root")
                for r in json.loads(gzip.decompress(raw))["rows"] if r["feedback"]["eligible"]]
    if len(rows) < 2:
        raise ValueError("Expected at least two certified trajectories")
    compared = []
    for width in (1, config["microbatch"]):
        policy = Policy().eval()
        policy.load_state_dict(initial["model"])
        optimizer = torch.optim.Adam(policy.parameters(),lr=config["learning_rate"])
        optimizer.load_state_dict(deepcopy(initial["adam"]))
        stats = optimize(policy, optimizer, rows, config | {"microbatch":width}, initial["model_sha256"])
        compared.append((policy,stats))
    (left,a),(right,b) = compared
    first = targets.Decision(rows[0]["transitions"][0]["observation"])
    with torch.no_grad():
        l,r = [p(first,torch.zeros(p.history.hidden_size))[:2] for p in (left,right)]
    objective_errors = {k:abs(a[k]-b[k]) for k in ("actor_loss","critic_loss","entropy","grad_norm")}
    assert all(abs(a[k]-b[k]) <= max(3e-3,5e-6*abs(a[k])) for k in objective_errors)
    probability_error = (l[0].softmax(0)-r[0].softmax(0)).abs().max().item()
    value_error = (l[1]-r[1]).abs().item()
    assert probability_error < 2e-5 and value_error < 2e-5
    return dict(objectives=objective_errors, sample_probability_error=probability_error,
                sample_value_error=value_error, scalar_logp_error=a["logp_error"], batched_logp_error=b["logp_error"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger",type=Path)
    parser.add_argument("config",type=Path)
    a=parser.parse_args()
    torch.set_num_threads(1)
    objective_checks()
    save_json(a.ledger/"numeric.json",numeric(a.ledger,json.loads(a.config.read_bytes())))
