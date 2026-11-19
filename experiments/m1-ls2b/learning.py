"""Root-balanced ridge proposal utility. Fit only on open development experience."""
from collections import Counter
import numpy as np

from spec import PARAMS, VERSION, digest

MODEL = "ls2b.ridge.v1"


def features(ctx, s):
    # Interactions allow a weight or switch to mean something different under HP pressure.
    state = [1, ctx["hp"], min(2, ctx["pressure"]), ctx["missing"], ctx["setup"],
             ctx["attack"], ctx["block"], min(3, ctx["enemies"])/3]
    params = [1, s["setup_turns"]/5, s["finish_pct"]/100, s["reserve_pct"]/100,
              float(s["target"] == "threat"), float(s["target"] == "largest")]
    for phase in ("opening", "finish"):
        params.extend(s[phase][k]/v for k, v in zip(PARAMS, (12, 12, 60, 40, 24)))
    return np.outer(state, params).ravel()


def fit(rows, binding):
    data = []
    seen = set()
    for row in rows:
        if row["split"] != "development":
            raise ValueError("Report or pilot data in fit")
        for a in row["attempts"]:
            key = (row["root"], a["strategy_hash"], a["allocated"])
            if key in seen or a["allocated"] != 48 or a.get("risks"):
                continue
            target = a["status"]
            if target not in ("qualified_win", "death", "action_cap"):
                continue
            seen.add(key)
            y = 1 + .2*a["resource"]["hp"]/a["resource"]["max_hp"] if target == "qualified_win" else 0
            data.append((row["root"], features(row["context"], a["strategy_spec"]), y))
    if not data or not any(y for _, _, y in data):
        raise ValueError("No verified development positives for proposal fitting")
    counts = Counter(root for root, _, _ in data)
    x = np.stack([f for _, f, _ in data])
    y = np.array([v for _, _, v in data])
    weight = np.array([1/counts[root] for root, _, _ in data])
    xtw = x.T * weight
    beta = np.linalg.solve(xtw @ x + 0.5*np.eye(x.shape[1]), xtw @ y)
    return dict(version=MODEL, spec_version=VERSION, binding=binding, coefficients=beta.tolist(),
                roots=sorted(counts), samples=len(data), positives=int(sum(y > 0)),
                supervision=digest([(root, f.tolist(), v) for root, f, v in data]))


def rank(ctx, proposals, model):
    if model["version"] != MODEL or model["spec_version"] != VERSION:
        raise ValueError("Proposal model version mismatch")
    beta = np.array(model["coefficients"])
    if beta.shape != (128,) or not np.isfinite(beta).all():
        raise ValueError("Invalid proposal coefficients")
    return sorted(proposals, key=lambda p: -float(features(ctx, p["strategy_spec"]) @ beta))
