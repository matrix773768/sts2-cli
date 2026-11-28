"""Exploratory offline-only architecture comparison using the exact 5G scratch MC schedule."""
import pickle
import sys
import time

from fit5h import E, G, W, active_data, active_metrics, learn, network, read, save, sha, torch
from settings import A


def main(seed):
    started = time.perf_counter()
    torch.set_num_threads(1)
    with (W / "corpus.pkl").open("rb") as handle:
        train, dev, suffix = pickle.load(handle)
    old = set(read(G.parent / "m1-core5f/evidence/split.json")["dev"])
    mask = torch.tensor([family in old for family in dev.family])
    order = read(A / "splits.json")["primary_train"]
    active, _ = active_data()
    panel = {}
    for kind in ("pool", "local", "interact"):
        stem = f"scratch-4096-{seed}"
        if kind == "pool":
            dest = G / "evidence"
            fit = read(dest / (stem + ".json"))
        else:
            dest = E / "scratch" / kind
            dest.mkdir(parents=True, exist_ok=True)
            learn.OUT = dest
            learn.Value = lambda: network(kind)
            fit = learn.run("scratch-4096", seed, train, dev, suffix, mask, order)
            save(dest / (stem + ".json"), fit)
        checkpoint = dest / (stem + ".pt")
        assert sha(checkpoint) == fit["sha256"]
        model = network(kind).eval()
        model.load_state_dict(torch.load(checkpoint, weights_only=True))
        best = next(r for r in fit["curve"] if r["step"] == fit["best_step"])
        metrics = active_metrics(model, active["dev"])
        record = dict(step=best["step"], natural=best["natural"]["all"],
                      old_pair_rmse=best["pair_rmse"], active=metrics, sha256=fit["sha256"])
        if kind != "pool":
            model.transform.forward = lambda values, mask: values
            after = active_metrics(model, active["dev"])
            record["changed_without_residual"] = sum((x > 0) != (y > 0)
                                                     for x, y in zip(metrics["delta"], after["delta"], strict=True))
            record["mean_abs_gap_change"] = sum(abs(x-y) for x,y in zip(metrics["delta"],after["delta"],strict=True))/len(metrics["delta"])
        panel[kind] = record
    save(E / f"scratch-{seed}.json", dict(models=panel, seconds=time.perf_counter()-started))


if __name__ == "__main__":
    main(int(sys.argv[1]))
