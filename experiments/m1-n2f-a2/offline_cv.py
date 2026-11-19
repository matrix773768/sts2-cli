"""Offline three-class CV. The parent experiment provides encoders and hidden layers."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
from time import perf_counter, perf_counter_ns
import tracemalloc

import numpy as np

from offline_data import HERE, LABELS, digest, fold_plan, load, load_catalog, read, require, save
import learning as parent

MODES = ("prior", *parent.MODES)


def softmax(logits):
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def init(inputs, width, seed):
    parameters = parent.init(inputs, width, seed)
    output_width = parameters["out_w"].size
    parameters["out_w"] = np.random.default_rng(seed + 1000).normal(0, .05, (output_width, 3))
    parameters["out_b"] = np.zeros(3)
    return parameters


def forward(parameters, inputs):
    # Keep the parent's hidden layers and use a three-logit head.
    common, cards = inputs
    if "card_w" not in parameters:
        return softmax(common @ parameters["out_w"] + parameters["out_b"]), common, None, None
    card_hidden = np.tanh(cards @ parameters["card_w"] + parameters["card_b"])
    pooled = np.concatenate((common, card_hidden.mean(axis=1)), axis=1)
    joint = np.tanh(pooled @ parameters["joint_w"] + parameters["joint_b"])
    return softmax(joint @ parameters["out_w"] + parameters["out_b"]), joint, pooled, card_hidden


def gradients(parameters, inputs, labels, l2):
    p, joint, pooled, card_hidden = forward(parameters, inputs)
    error = (p - np.eye(3)[labels]) / len(labels)
    result = dict(out_w=joint.T @ error, out_b=error.sum(axis=0))
    if card_hidden is not None:
        joint_signal = (error @ parameters["out_w"].T) * (1 - joint**2)
        result.update(joint_w=pooled.T @ joint_signal, joint_b=joint_signal.sum(axis=0))
        propagated = joint_signal @ parameters["joint_w"][-card_hidden.shape[-1]:].T
        signal = propagated[:, None, :] * (1 - card_hidden**2) / card_hidden.shape[1]
        result.update(card_w=inputs[1].reshape(-1, inputs[1].shape[-1]).T @ signal.reshape(-1, signal.shape[-1]),
                      card_b=signal.sum(axis=(0, 1)))
    return {key: value + (l2 * parameters[key] if key.endswith("_w") else 0) for key, value in result.items()}


def fit(inputs, labels, cfg, seed, deadline):
    parameters = init(inputs, cfg["hidden"], seed)
    moments = {k: np.zeros_like(v) for k, v in parameters.items()}
    squares = {k: np.zeros_like(v) for k, v in parameters.items()}
    for epoch in range(1, cfg["epochs"] + 1):
        if perf_counter() > deadline:
            raise TimeoutError("Frozen fit budget expired")
        for key, gradient in gradients(parameters, inputs, labels, cfg["l2"]).items():
            moments[key] = .9 * moments[key] + .1 * gradient
            squares[key] = .999 * squares[key] + .001 * gradient**2
            parameters[key] -= cfg["learning_rate"] * (moments[key] / (1 - .9**epoch)) / (
                np.sqrt(squares[key] / (1 - .999**epoch)) + 1e-8)
    require(all(np.isfinite(v).all() for v in parameters.values()), "Nonfinite trained parameters")
    return parameters


def stratum(row):
    return row["audit"]["family"], row["input"]["encounter"]


def prior(records, labels, alpha):
    counts = defaultdict(lambda: np.full(3, alpha, dtype=float))
    for row, label in zip(records, labels, strict=True):
        counts[stratum(row)][label] += 1
    return {key: value / value.sum() for key, value in counts.items()}


def metrics(y, p):
    selected = p.argmax(axis=1)
    matrix = np.zeros((3, 3), dtype=int)
    np.add.at(matrix, (y, selected), 1)
    counts = matrix.sum(axis=1)
    return dict(n=len(y), log_loss=float(-np.log(np.maximum(p[np.arange(len(y)), y], 1e-15)).mean()),
                brier=float(np.mean(np.sum((p - np.eye(3)[y])**2, axis=1))),
                accuracy=float(np.mean(y == selected)), confusion=matrix.tolist(),
                recall=[float(matrix[i, i]/count) if count else None for i, count in enumerate(counts)],
                actual_frequency=(counts/len(y)).tolist(), predicted_mean=p.mean(axis=0).tolist())


def interaction(rows, y, probabilities):
    blocks = defaultdict(dict)
    for i, row in enumerate(rows):
        a = row["audit"]
        blocks[a["family"], a["pair"]][a["slot_a"], a["slot_b"]] = i
    answer = {}
    for family in sorted({key[0] for key in blocks}):
        indices = np.array([[v[0, 0], v[1, 0], v[0, 1], v[1, 1]]
                            for key, v in blocks.items() if key[0] == family])
        actual = np.eye(3)[y][indices]
        def summarize(values):
            cells = values.mean(axis=0)
            return dict(cells=cells.tolist(), contrast=(cells[3] - cells[1] - cells[2] + cells[0]).tolist())
        answer[family] = dict(blocks=len(indices), actual=summarize(actual),
                              models={name: summarize(p[indices]) for name, p in probabilities.items()})
    return answer


def paired_uncertainty(rows, y, probabilities, config):
    families = defaultdict(dict)
    for i, row in enumerate(rows):
        a = row["audit"]
        families[a["family"]].setdefault(a["template"], []).append(i)
    groups = [np.array(list(templates.values())) for templates in families.values()]
    rng = np.random.default_rng(config["seed"])
    indices = np.concatenate([g[rng.integers(len(g), size=(config["replicates"], len(g)))].reshape(
        config["replicates"], -1) for g in groups], axis=1)
    errors = {mode: -np.log(np.maximum(p[np.arange(len(y)), y], 1e-15))
              for mode, p in probabilities.items()}
    return {mode: np.percentile((errors["mechanics"] - error)[indices].mean(axis=1), [2.5, 97.5]).tolist()
            for mode, error in errors.items() if mode != "mechanics"}


def run(output):
    began = perf_counter()
    rows = load()
    cfg = read(HERE / "protocol.json")
    require(digest(rows) == cfg["records_sha256"] and fold_plan(rows) == cfg["folds"], "Offline lock differs")
    require(cfg["new_rollouts"] == 0 and cfg["action_cap"] == 96, "Unexpected target")
    ids = np.array([r["audit"]["id"] for r in rows])
    y = np.array([LABELS[r["status"]] for r in rows])
    predictions = {mode: np.full((len(y), 3), np.nan) for mode in MODES}
    catalog = load_catalog()
    tracemalloc.start()
    prep = perf_counter()
    features = {mode: parent.stacked(rows, mode, catalog, cfg["card_dim"]) for mode in parent.MODES}
    encoding_seconds = perf_counter() - prep
    deadline = perf_counter() + cfg["fit_wall_limit_seconds"]
    folds, models = [], []
    for fold in cfg["folds"]:
        mask = np.isin(ids, fold["held_ids"])
        train, held = np.flatnonzero(~mask), np.flatnonzero(mask)
        require(len(train) == 256 and len(held) == 64, "Incorrect fold size")
        train_rows = [rows[i] for i in train]
        fit_start = perf_counter()
        table = prior(train_rows, y[train], cfg["prior"]["laplace_alpha"])
        train_p = np.stack([table[stratum(r)] for r in train_rows])
        held_p = np.stack([table[stratum(rows[i])] for i in held])
        ticks = [0.0] * len(held)
        for n, i in enumerate(held):
            t = perf_counter_ns()
            table[stratum(rows[i])]
            ticks[n] = (perf_counter_ns() - t) / 1e6
        model_records = {"prior": dict(train=metrics(y[train], train_p), held=metrics(y[held], held_p),
                              fit_seconds=perf_counter() - fit_start, independent_parameters=len(table)*2,
                              inference_ms=np.percentile(ticks, [50, 95]).tolist())}
        predictions["prior"][held] = held_p
        models.append(dict(fold=fold["index"], mode="prior",
                           table=[{"family": k[0], "encounter": k[1], "probabilities": v.tolist()}
                                  for k, v in sorted(table.items())]))
        for mode, x in features.items():
            x_train = tuple(v[train] for v in x)
            x_held = tuple(v[held] for v in x)
            fit_start = perf_counter()
            ensemble = [fit(x_train, y[train], cfg, seed, deadline) for seed in cfg["seed"]]
            fit_seconds = perf_counter() - fit_start
            train_p = np.mean([forward(p, x_train)[0] for p in ensemble], axis=0)
            held_runs = [forward(p, x_held)[0] for p in ensemble]
            held_p = np.mean(held_runs, axis=0)
            predictions[mode][held] = held_p
            ticks = []
            for i in held:
                tick = perf_counter_ns()
                single = tuple(v[i:i+1] for v in x)
                np.mean([forward(p, single)[0] for p in ensemble], axis=0)
                ticks.append((perf_counter_ns() - tick) / 1e6)
            model_records[mode] = dict(train=metrics(y[train], train_p), held=metrics(y[held], held_p),
                 seeds_held_log_loss=[metrics(y[held], pr)["log_loss"] for pr in held_runs],
                 fit_seconds=fit_seconds, parameters_per_seed=sum(v.size for v in ensemble[0].values()),
                 inference_ms=np.percentile(ticks, [50, 95]).tolist())
            payload = [{k: v.tolist() for k, v in p.items()} for p in ensemble]
            models.append(dict(fold=fold["index"], mode=mode, parameters=payload, sha256=digest(payload)))
        folds.append(dict(index=fold["index"], groups=fold["held_groups"], models=model_records))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    for p in predictions.values():
        require(np.isfinite(p).all() and np.allclose(p.sum(axis=1), 1), "Incomplete probabilities")
    strata = defaultdict(list)
    for i, row in enumerate(rows):
        family, encounter = stratum(row)
        for key in ("all", family, encounter, f"{family}/{encounter}", row["audit"]["template"]):
            strata[key].append(i)
    scores = {name: {mode: metrics(y[index], p[index]) for mode, p in predictions.items()}
              for name, index in strata.items()}
    record = dict(scope=cfg["scope"], protocol_sha256=digest(cfg), numpy=np.__version__,
                  encoding_seconds=encoding_seconds, peak_traced_bytes=peak, wall_seconds=perf_counter()-began,
                  scores=scores, folds=folds, factorial=interaction(rows, y, predictions),
                  paired_log_loss_delta_ci=paired_uncertainty(rows, y, predictions, cfg["bootstrap"]))
    output.mkdir(parents=True, exist_ok=True)
    save(output / "results.json", record)
    save(output / "predictions.json", [dict(id=r["audit"]["id"], group=r["audit"]["template"],
                                            label=int(y[i]), probabilities={k: p[i].tolist()
                                            for k, p in predictions.items()}) for i, r in enumerate(rows)])
    model_bundle = dict(protocol_sha256=digest(cfg), models=models)
    packed = json.dumps(dict(model_bundle, sha256=digest(model_bundle)),
                        separators=(",", ":"), allow_nan=False).encode("utf-8")
    (output / "weights.json.gz").write_bytes(gzip.compress(packed, mtime=0))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output.resolve())
