"""Compare reference and candidate updates on identical public ledgers and Adam state."""
import argparse
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from time import perf_counter

import torch

from batched import forward
from features import BASE, HERE, FastDecision, card_rules, protocol
from journal import load as restore
from learning import train as reference
from nosl3b_store import tensors, unpack
from nosl_experience import save_json, targets
from nosl_model import Decision, WIDTH
import optimizer
import profile_stock

LIMITS = json.loads((HERE / "performance.json").read_bytes())
# This scalar translates every legal logit equally. It is unidentifiable by
# softmax and analytically has exactly zero gradient under both actor terms.
LOGIT_OFFSET = "actor.1.bias"


class Witness(list):
    def __init__(self):
        super().__init__()
        self.gradients = {}


def load(saved, cfg, step):
    # CPU Adam can alias its input moment tensors. Each arm starts with its own copy.
    return restore(deepcopy(saved), cfg, step)


def database(path):
    return closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True))


def snapshot(db, step):
    raw, = db.execute("SELECT payload FROM snapshots WHERE step=?", (step,)).fetchone()
    return tensors(raw)


def rows_at(db, stage):
    return [r for raw, in db.execute("SELECT rows FROM roots WHERE phase='train' AND step=? ORDER BY root", (stage,))
            for r in unpack(raw)["rows"]]


@torch.no_grad()
def predict(model, episodes, batch_size=16):
    observations = [list(r["transitions"]) for r in episodes]
    observations = sorted(filter(None, observations), key=len, reverse=True)
    deltas = dict(values=0., probability=0., logit=0., memory=0., states=0)
    for i in range(0, len(observations), batch_size):
        group = observations[i:i+batch_size]
        history = torch.zeros((len(group), WIDTH))
        other = history.clone()
        for t in range(len(group[0])):
            active = [steps[t] for steps in group if len(steps) > t]
            fast = [FastDecision(s["observation"]) for s in active]
            logits, val, state, actions, mask = forward(model, fast, history[:len(active)])
            assert torch.equal(torch.isfinite(logits), mask)
            next_other = []
            chosen = torch.tensor([s["action"]["index"] for s in active])
            history = model.history(torch.cat((state, actions[torch.arange(len(chosen)), chosen]), dim=1),
                                    history[:len(active)])
            for j, s in enumerate(active):
                decision = Decision(s["observation"])
                for key, actual in vars(fast[j]).items():
                    expected = getattr(decision, key)
                    assert torch.equal(actual, expected) if isinstance(actual, torch.Tensor) else actual == expected
                ref_l, ref_v, ref_state, ref_a = model(decision, other[j])
                next_other.append(model.remember(other[j], ref_state, ref_a[chosen[j]]))
                assert int(mask[j].sum()) == len(ref_l)
                logit = logits[j, mask[j]]
                deltas["values"] = max(deltas["values"], (val[j] - ref_v).abs().max().item())
                deltas["logit"] = max(deltas["logit"], (logit - ref_l).abs().max().item())
                deltas["probability"] = max(deltas["probability"], (logit.softmax(0) - ref_l.softmax(0)).abs().max().item())
                deltas["memory"] = max(deltas["memory"], (history[j] - next_other[-1]).abs().max().item())
                deltas["states"] += 1
            other = torch.stack(next_other)
    assert deltas["values"] <= LIMITS["value_max_abs"]
    assert deltas["probability"] <= LIMITS["probability_max_abs"]
    return deltas


def difference(actual, expected, tolerance):
    assert expected.keys() == actual.keys()
    max_abs, squared_error, squared_reference = 0., 0., 0.
    for name, ref in expected.items():
        candidate = actual[name]
        torch.testing.assert_close(candidate, ref, msg=lambda detail: f"{name}: {detail}",
                                   atol=tolerance["atol"], rtol=tolerance["rtol"])
        error = (candidate - ref).double()
        max_abs = max(max_abs, error.abs().max().item())
        squared_error += error.square().sum().item()
        squared_reference += ref.double().square().sum().item()
    relative_l2 = (squared_error / max(squared_reference, 1e-30)) ** .5
    if "relative_l2_max" in tolerance:
        assert relative_l2 <= tolerance["relative_l2_max"]
    return dict(max_abs=max_abs, relative_l2=relative_l2, tensors=len(expected))


def compare_update(saved, rows, cfg, step, *, exact=True, modes=("micro", "features", "batched"),
                   candidate_threads=1, microbatch=16):
    eligible = [r for r in rows if targets(r["feedback"]) is not None]
    w = Witness()
    model, adam = load(saved, cfg, step)
    before = predict(model, eligible)
    ref = profile_stock.train(model, adam, rows, cfg, saved["model_sha256"], witness=w)
    if exact:
        original, original_adam = load(saved, cfg, step)
        pristine = reference(original, original_adam, rows, cfg, saved["model_sha256"])
        assert pristine["model_sha256"] == ref["model_sha256"]
    results = dict(step=step, before=before, reference=ref, variants={})
    for mode in modes:
        updated, opt = load(saved, cfg, step)
        optimized = Witness()
        torch.set_num_threads(candidate_threads)
        try:
            s = optimizer.train(updated, opt, rows, cfg, saved["model_sha256"], mode=mode,
                                microbatch=microbatch, witness=optimized)
        finally:
            torch.set_num_threads(1)
        assert len(w) == len(optimized) == ref["steps"]
        if mode != "batched" and candidate_threads == 1:
            assert all(torch.equal(a, b) for old, new in zip(w, optimized, strict=True)
                       for a, b in zip(old, new, strict=True))
        deltas = {}
        for key in ("actor_loss", "critic_loss", "entropy_sum_per_episode", "actor_gradient", "critic_gradient_after_clip"):
            limit = LIMITS["loss"]
            delta = abs(s[key]-ref[key])
            assert delta <= limit["atol"] + limit["rtol"] * abs(ref[key]), (key, mode, delta)
            deltas[key] = delta
        assert s["qualified"] == ref["qualified"] and s["steps"] == ref["steps"]
        assert s["logp_error"] <= LIMITS["behavior_logp_max_abs"]
        g = difference(optimized.gradients, w.gradients, LIMITS["gradient"])
        left, right = updated.state_dict(), model.state_dict()
        shift = (left[LOGIT_OFFSET] - right[LOGIT_OFFSET]).abs().item()
        limit = LIMITS["parameter"]
        p = difference({k: v for k, v in left.items() if k != LOGIT_OFFSET},
                       {k: v for k, v in right.items() if k != LOGIT_OFFSET}, limit)
        p["offset_abs"] = shift
        p["offset_passes_raw_parameter_limit"] = shift <= limit["atol"] + limit["rtol"] * right[LOGIT_OFFSET].abs().item()
        p["full_raw_max_abs"] = max(shift, p["max_abs"])
        p["offset_reference_gradient"] = w.gradients[LOGIT_OFFSET].item()
        p["offset_candidate_gradient"] = optimized.gradients[LOGIT_OFFSET].item()
        output = predict(updated, eligible[:4])
        for a, b in zip(scalar_predictions(updated, eligible[:4]), scalar_predictions(model, eligible[:4]), strict=True):
            output.setdefault("updated_policy_probability", 0.)
            output.setdefault("updated_policy_values", 0.)
            output["updated_policy_probability"] = max(output["updated_policy_probability"],
                                                         (a[0] - b[0]).abs().max().item())
            output["updated_policy_values"] = max(output["updated_policy_values"], (a[1] - b[1]).abs().max().item())
        assert output["updated_policy_probability"] <= LIMITS["probability_max_abs"]
        assert output["updated_policy_values"] <= LIMITS["value_max_abs"]
        results["variants"][mode] = dict(metrics=s, loss_deltas=deltas, gradients=g, parameters=p, after=output)
    if "micro" in results["variants"] and "features" in results["variants"]:
        assert results["variants"]["micro"]["metrics"]["model_sha256"] == results["variants"]["features"]["metrics"]["model_sha256"]
    return results


@torch.no_grad()
def scalar_predictions(model, episodes):
    for row in episodes:
        h = torch.zeros(WIDTH)
        for s in row["transitions"]:
            logits, value, state, actions = model(Decision(s["observation"]), h)
            yield logits.softmax(0), value
            h = model.remember(h, state, actions[s["action"]["index"]])


def feature_times(rows):
    observations = [s["observation"] for row in rows for s in row["transitions"]]
    results = {"observations": len(observations)}
    card_rules.cache_clear()
    for cls in (Decision, FastDecision):
        elapsed = []
        for _ in range(3):
            tick = perf_counter()
            for obs in observations:
                cls(obs)
            elapsed.append(perf_counter() - tick)
        results[cls.__name__] = elapsed
    results["static_cache"] = card_rules.cache_info()._asdict()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=BASE / "formal.json")
    parser.add_argument("--step", type=int, nargs="+", default=[0])
    parser.add_argument("--threads", type=int, nargs="+", default=[1])
    parser.add_argument("--tuned", action="store_true", help="Verify the four-thread 32-episode tuning candidate")
    args = parser.parse_args()
    cfg = protocol.read(args.config)
    torch.use_deterministic_algorithms(True)
    all_results = []
    with database(args.ledger) as db:
        for step in args.step:
            saved, rows = snapshot(db, step), rows_at(db, step)
            torch.set_num_threads(1)
            settings = dict(candidate_threads=4, microbatch=32, modes=("batched",)) if args.tuned else {}
            comparison = compare_update(saved, rows, cfg, step, **settings)
            comparison["matches_archived_checkpoint"] = (
                comparison["reference"]["model_sha256"] == snapshot(db, step+1)["model_sha256"])
            assert comparison["matches_archived_checkpoint"]
            all_results.append(comparison | dict(feature_bench=feature_times(rows)))
            save_json(args.output, dict(limits=LIMITS, results=all_results))
            for threads in (() if args.tuned else args.threads):
                torch.set_num_threads(threads)
                model, adam = load(saved, cfg, step)
                all_results.append(dict(step=step, threads=threads,
                                        sweep=optimizer.train(model, adam, rows, cfg, saved["model_sha256"])))
        torch.set_num_threads(1)
        step = args.step[0]
        saved, rows = snapshot(db, step), rows_at(db, step)
        for m in (() if args.tuned else LIMITS["microbatch_sweep"]):
            model, adam = load(saved, cfg, step)
            all_results.append(dict(step=step, microbatch=m,
                                    sweep=optimizer.train(model, adam, rows, cfg, saved["model_sha256"], microbatch=m)))
    save_json(args.output, dict(limits=LIMITS, results=all_results))


if __name__ == "__main__":
    main()
