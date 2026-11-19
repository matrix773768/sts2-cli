"""Fit capacity-matched deck models and score the held-out factorial arms."""
import argparse
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path
from time import perf_counter, perf_counter_ns
import tracemalloc

import numpy as np

from study_design import HERE, ENCOUNTERS, FAMILIES, digest, read, save, load_catalog, deck_from_root
from rollout import NORMAL, qualify_audit, rows, text_hash

KINDS = ("Damage", "Block", "Draw", "Discard", "GenerateCard", "GainEnergy", "ApplyPower",
         "GainPower", "Exhaust", "ConditionalEffect", "TriggeredEffect", "UnsupportedEffect")
MODES = ("statistics", "identity", "mechanics")


def walk(value, path=()):
    if isinstance(value, dict):
        for key, child in sorted(value.items()):
            yield from walk(child, (*path, key))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from walk(child, (*path, i))
    else:
        yield path, value


def vector(card, width):
    """Fixed signed featurization. Positions preserve node order at every depth."""
    result = np.zeros(width)
    for path, value in walk(card):
        if type(value) in (int, float):
            token = path, "number"
            weight = value / (20 if path[-1] == "amount" else 4)
        else:
            token = path, value
            weight = 1
        key = bytes.fromhex(digest(token))
        result[int.from_bytes(key[:4], "big") % width] += weight if key[4] & 1 else -weight
    return result


def context(spec):
    return [spec["hp"] / 80, spec["max_hp"] / 80, spec["ascension"] / 20, spec["act"] / 3,
            *(int(spec["character"] == character) for character, _, _ in FAMILIES.values()),
            *(int(spec["encounter"] == encounter) for encounter in ENCOUNTERS),
            *(int(relic in spec["relics"]) for relic in ("BURNING_BLOOD", "RING_OF_THE_SNAKE")),
            sum(p is not None for p in spec["potions"]) / 3]


def encode(spec, mode, catalog, width):
    deck = deck_from_root(spec["character"], spec["deck"])
    view = catalog.encode_deck(deck, "identity" if mode == "identity" else "mechanics")
    common = context(spec)
    size = len(deck.cards)
    if mode == "statistics":
        counts = Counter()
        cost = upgrades = 0
        for entry in view["cards"]:
            card, count = entry["card"], entry["count"]
            cost += count * (card["cost"] or 0)
            upgrades += count * card["upgrade_level"]
            for node in card["effects"]:
                counts[node["kind"]] += count
                counts[node["kind"] + ".amount"] += count * node.get("amount", node.get("count", 0))
        return np.array(common + [size / 20, cost / size, upgrades / size]
                        + [counts[k] / size for k in KINDS]
                        + [counts[k + ".amount"] / (size * 10) for k in KINDS]), np.empty((0, width))
    return np.array(common + [size / 20]), np.stack([
        vector(entry["card"], width) for entry in view["cards"] for _ in range(entry["count"])
    ])


def sigmoid(logit):
    return 1 / (1 + np.exp(-np.clip(logit, -35, 35)))


def forward(parameters, inputs):
    common, cards = inputs
    if "card_w" in parameters:
        card_hidden = np.tanh(cards @ parameters["card_w"] + parameters["card_b"])
        pooled = np.concatenate((common, card_hidden.mean(axis=1)), axis=1)
        joint = np.tanh(pooled @ parameters["joint_w"] + parameters["joint_b"])
    else:
        card_hidden = pooled = None
        joint = common
    return sigmoid(joint @ parameters["out_w"] + parameters["out_b"]), joint, pooled, card_hidden


def init(inputs, hidden, seed):
    rng = np.random.default_rng(seed)
    common, cards = inputs
    width = cards.shape[-1]
    is_deep_set = bool(cards.shape[1])
    parameters = {"out_w": rng.normal(0, .05, hidden if is_deep_set else common.shape[-1]),
                  "out_b": np.zeros(())}
    if is_deep_set:
        joint_width = common.shape[-1] + hidden
        parameters.update(card_w=rng.normal(0, 1 / np.sqrt(width), (width, hidden)), card_b=np.zeros(hidden),
                          joint_w=rng.normal(0, 1 / np.sqrt(joint_width), (joint_width, hidden)),
                          joint_b=np.zeros(hidden))
    return parameters


def gradients(parameters, inputs, labels, l2):
    prediction, joint, pooled, card_hidden = forward(parameters, inputs)
    error = (prediction - labels) / labels.size
    result = dict(out_w=joint.T @ error, out_b=error.sum())
    if card_hidden is not None:
        joint_signal = error[:, None] * parameters["out_w"] * (1 - joint**2)
        result.update(joint_w=pooled.T @ joint_signal, joint_b=joint_signal.sum(axis=0))
        pooled_signal = joint_signal @ parameters["joint_w"][-card_hidden.shape[-1]:].T
        signal = pooled_signal[:, None, :] * (1 - card_hidden**2) / card_hidden.shape[1]
        result.update(card_w=inputs[1].reshape(-1, inputs[1].shape[-1]).T @ signal.reshape(-1, card_hidden.shape[-1]),
                      card_b=signal.sum(axis=(0, 1)))
    return {key: value + (l2 * parameters[key] if key.endswith("_w") else 0) for key, value in result.items()}


def fit(inputs, labels, cfg, seed, deadline):
    parameters = init(inputs, cfg["hidden"], seed)
    moments = {k: np.zeros_like(v) for k, v in parameters.items()}
    squares = {k: np.zeros_like(v) for k, v in parameters.items()}
    for epoch in range(1, max(cfg["epochs"]) + 1):
        if perf_counter() >= deadline:
            raise TimeoutError("Frozen model training wall limit exceeded")
        for key, value in gradients(parameters, inputs, labels, cfg["l2"]).items():
            moments[key] = .9 * moments[key] + .1 * value
            squares[key] = .999 * squares[key] + .001 * value**2
            parameters[key] -= (cfg["learning_rate"] * moments[key] / (1 - .9**epoch)
                                / (np.sqrt(squares[key] / (1 - .999**epoch)) + 1e-8))
        if epoch in cfg["epochs"]:
            yield epoch, {k: v.copy() for k, v in parameters.items()}


def stacked(records, mode, catalog, width):
    left, right = zip(*(encode(row["input"], mode, catalog, width) for row in records))
    return np.stack(left), np.stack(right)


def data(output, phase):
    manifest = read(HERE / "manifest.json")
    cases = {r["case"]["id"]: r for r in manifest if r["case"]["cohort"] == phase}
    ledger = {r["id"]: r for r in rows(output / "ledger.jsonl") if r["id"] in cases}
    if set(ledger) != set(cases):
        raise ValueError(f"Incomplete {phase} ledger")
    result = []
    for key, item in cases.items():
        case = item["case"]
        terminal = ledger[key]["terminal"]
        status = terminal["status"]
        entry = {k: v for k, v in case.items() if k != "spec"}
        entry.update(synthetic=item["synthetic"], natural_reachability=item["natural_reachability"])
        fields = ("character", "hp", "max_hp", "encounter", "ascension", "act", "relics", "potions", "deck")
        spec = {key: case["spec"][key] for key in fields}
        resource = terminal["feedback"]["combat_terminal"] if status in NORMAL else None
        missing = None if status in NORMAL else (
            (terminal.get("feedback") or {}).get("missing_reason") or terminal.get("detail") or status)
        result.append(dict(audit=entry, input=spec, status=status, missing_reason=missing,
                           evidence=ledger[key].get("evidence"),
                           label=int(status == "predicted_win") if status in NORMAL else None,
                           winning_hp=resource["hp"] if status == "predicted_win" else None))
    return result


def train(output):
    protocol = read(HERE / "protocol.json")
    cfg = protocol["training"]
    qualify_audit(output)
    if (output / "models.json").exists() or any(r["phase"] == "report" for r in rows(output / "budget.jsonl")):
        raise ValueError("Training is locked after the model bundle or report reservation exists")
    data_started = perf_counter()
    catalog = load_catalog()
    development = {phase: data(output, phase) for phase in ("train", "selection")}
    save(output / "development.json", development)
    data_seconds = perf_counter() - data_started
    training, selection = ([r for r in development[phase] if r["label"] is not None]
                           for phase in ("train", "selection"))
    groups = {family: sorted({r["audit"]["template"] for r in training if r["audit"]["family"] == family})
              for family in FAMILIES}
    models = []
    tracemalloc.start()
    start = perf_counter()
    for mode, size in product(MODES, cfg["subsample_groups"]):
        tick = perf_counter()
        selected = {g for family in groups.values() for g in family[:size // 2]}
        subset = [r for r in training if r["audit"]["template"] in selected]
        x = stacked(subset, mode, catalog, cfg["card_dim"])
        val = stacked(selection, mode, catalog, cfg["card_dim"])
        y = np.array([r["label"] for r in subset])
        val_y = np.array([r["label"] for r in selection])
        fit_started = perf_counter()
        checkpoints = defaultdict(list)
        for seed in cfg["seeds"]:
            for epoch, params in fit(x, y, cfg, seed, start + cfg["training_wall_limit_seconds"]):
                checkpoints[epoch].append((params, forward(params, val)[0]))
        scores = {epoch: float(np.mean((np.mean([p for _, p in runs], axis=0) - val_y)**2))
                  for epoch, runs in checkpoints.items()}
        epoch = min(scores, key=lambda step: (scores[step], step))
        params = [p for p, _ in checkpoints[epoch]]
        finished = perf_counter()
        models.append(dict(mode=mode, groups=size, n=len(subset), train_groups=sorted(selected), epochs=epoch,
                           selection_brier=scores[epoch], selection_curve={str(k): v for k, v in scores.items()},
                           params_per_seed=sum(v.size for v in params[0].values()),
                           parameters=[{k: v.tolist() for k, v in run.items()} for run in params],
                           encoding_seconds=fit_started - tick, fit_seconds=finished - fit_started,
                           wall_seconds=finished - tick))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    for model in models:
        model["parameters_sha256"] = digest(model["parameters"])
    bundle = dict(protocol_sha256=digest(protocol), model_code_sha256=text_hash(Path(__file__)),
                  development_sha256=digest(development), numpy=np.__version__,
                  data_seconds=data_seconds, wall_seconds=perf_counter() - start, peak_traced_bytes=peak,
                  models=models)
    save(output / "models.json", bundle | dict(sha256=digest(bundle)))


def summary(records, predictions):
    indices = [i for i, r in enumerate(records) if r["label"] is not None]
    if not indices:
        return dict(n=len(records), normal=0, wins=0, brier=None, log_loss=None)
    y = np.array([records[i]["label"] for i in indices])
    p = np.clip(predictions[indices], 1e-8, 1 - 1e-8)
    return dict(n=len(records), normal=len(y), wins=int(y.sum()), brier=float(np.mean((p-y)**2)),
                log_loss=float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p))))


def factorial(records, p):
    blocks = defaultdict(dict)
    for row, probability in zip(records, p):
        audit = row["audit"]
        blocks[audit["pair"]][audit["slot_a"], audit["slot_b"]] = row, float(probability)
    result = []
    for pair, cells in blocks.items():
        if len(cells) != 4 or any(row["label"] is None for row, _ in cells.values()):
            continue
        def contrast(values):
            return values[1, 1] - values[1, 0] - values[0, 1] + values[0, 0]
        first = cells[0, 0][0]
        labels = {k: r["label"] for k, (r, _) in cells.items()}
        probs = {k: v for k, (_, v) in cells.items()}
        result.append(dict(pair=pair, family=first["audit"]["family"], recipe=first["audit"]["template"],
                           encounter=first["input"]["encounter"], observed=contrast(labels),
                           predicted=contrast(probs), observed_cells=list(labels.values()),
                           predicted_cells=list(probs.values())))
    return result


def report(output):
    started = perf_counter()
    protocol = read(HERE / "protocol.json")
    config = protocol["training"]
    bundle = read(output / "models.json")
    signature = bundle.pop("sha256")
    if (digest(bundle) != signature or bundle["protocol_sha256"] != digest(protocol)
            or bundle["model_code_sha256"] != text_hash(Path(__file__))):
        raise ValueError("Model lock differs")
    catalog = load_catalog()
    records = data(output, "report")
    save(output / "report-data.json", records)
    data_seconds = perf_counter() - started
    results = []
    for model in bundle["models"]:
        mode = model["mode"]
        x = stacked(records, mode, catalog, config["card_dim"])
        parameters = [{k: np.asarray(v) for k, v in p.items()} for p in model["parameters"]]
        predictions = np.mean([forward(p, x)[0] for p in parameters], axis=0)
        benchmark = []
        inference = []
        for i in range(len(records)):
            tick = perf_counter_ns()
            instance = tuple(a[None, ...] for a in encode(records[i]["input"], mode, catalog, config["card_dim"]))
            encoded_at = perf_counter_ns()
            for p in parameters:
                forward(p, instance)
            finished = perf_counter_ns()
            inference.append((finished - encoded_at) / 1e6)
            benchmark.append((finished - tick) / 1e6)
        slices = {}
        for family, encounter in product(FAMILIES, ENCOUNTERS):
            mask = [i for i, row in enumerate(records) if row["audit"]["family"] == family
                    and row["input"]["encounter"] == encounter]
            slices[f"{family}/{encounter}"] = summary([records[i] for i in mask], predictions[mask])
        calibration = []
        for lo, hi in zip(np.linspace(0, .8, 5), np.linspace(.2, 1, 5)):
            mask = [i for i, row in enumerate(records) if row["label"] is not None and lo <= predictions[i] < hi]
            calibration.append(dict(lo=lo, hi=hi, n=len(mask),
                                    mean_prediction=float(np.mean(predictions[mask])) if mask else None,
                                    observed=float(np.mean([records[i]["label"] for i in mask])) if mask else None))
        results.append(dict(mode=mode, groups=model["groups"], score=summary(records, predictions),
                            slices=slices, calibration=calibration, factorial=factorial(records, predictions),
                            probabilities=predictions.tolist(),
                            inference_ms=np.percentile(inference, [50, 95]).tolist(),
                            encoded_inference_ms=np.percentile(benchmark, [50, 95]).tolist()))
    by_recipe = defaultdict(list)
    full = {r["mode"]: r for r in results if r["groups"] == max(config["subsample_groups"])}
    for i, row in enumerate(records):
        if row["label"] is not None:
            y = row["label"]
            by_recipe[row["audit"]["template"]].append((full["mechanics"]["probabilities"][i]-y)**2
                                                       -(full["identity"]["probabilities"][i]-y)**2)
    rng = np.random.default_rng(771)
    boot = []
    for _ in range(2000):
        chosen = []
        for family in FAMILIES:
            keys = [k for k in by_recipe if k.startswith(family + "-")]
            chosen.extend(v for k in rng.choice(keys, size=len(keys)) for v in by_recipe[k])
        boot.append(np.mean(chosen))
    hp = [r["winning_hp"] for r in records if r["winning_hp"] is not None]
    save(output / "evaluation.json", dict(models_sha256=signature, results=results,
         delta_brier_cluster_bootstrap=np.percentile(boot, [2.5, 97.5]).tolist(),
         winning_hp=dict(n=len(hp), mean=float(np.mean(hp)) if hp else None),
         data_seconds=data_seconds, wall_seconds=perf_counter() - started,
         stops=dict(Counter(r["status"] for r in records))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("phase",choices=["train","report"])
    args = parser.parse_args()
    (train if args.phase == "train" else report)(args.output.resolve())
