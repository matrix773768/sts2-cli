"""Rebind frozen II-C action identities to the current menu and audit the replay."""
import argparse
from contextlib import ExitStack, closing
import gzip
import json
from pathlib import Path
import sqlite3

from targets import BANK, CAPTURE, configure, open_worker, project, worker_bind, certify
from nosl_experience import save_json, terminal


def key(action):
    return tuple(action.get(k) for k in ("kind", "card", "target", "choice", "potion"))


def replay(output, versions, spec, row):
    if not row["transitions"]:
        return dict(status="no_frozen_route")
    with ExitStack() as stack:
        game = open_worker(output, stack, versions)
        CAPTURE(game, spec)
        state = game.request("i1_n2_reset", arm="A", cap=len(row["transitions"]),
                             potions=False, rejected=[])["episode"]
        rebound = []
        previous = None
        for n, step in enumerate(row["transitions"]):
            if state["status"] != "active":
                return dict(status="prediction_stopped", position=n, detail=state.get("detail"))
            obs = project(state["observation"])
            before = step["observation"]
            fields = [k for k in before if k != "actions" and before[k] != obs[k]]
            if fields:
                return dict(status="public_prefix_difference", position=n, fields=fields)
            matching = [a for a in obs["actions"] if key(a) == key(step["action"])]
            if len(matching) != 1:
                return dict(status="binding_difference", position=n, action=step["action"])
            action, = matching
            rebound.append(dict(position=n, observation=obs, action=action))
            if obs["decision"]["phase"] == "combat":
                previous = action
            state = game.request("i1_n2_step", position=n, index=action["index"])["episode"]
        game.request("i1_n2_close")
    if not rebound:
        return dict(status="no_frozen_route")
    route = dict(transitions=rebound, feedback=terminal(state, previous))
    return certify(output, versions, spec, route) | {
        "rebound_indices": sum(a["action"]["index"] != b["action"]["index"]
                               for a, b in zip(rebound, row["transitions"], strict=True))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--solver", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    configure()
    versions = worker_bind(output, args.solver.resolve())
    results = []
    with closing(sqlite3.connect(args.baseline / "training.sqlite")) as db:
        for key_, packed in db.execute("SELECT root, rows FROM roots ORDER BY step, root"):
            batch = json.loads(gzip.decompress(packed))
            if not batch["rows"]:
                continue
            try:
                result = replay(output, versions, batch["spec"], batch["rows"][0])
            except (BANK.f1.i2.StopRun, ValueError, RuntimeError, KeyError) as error:
                result = dict(status="diagnostic_failure", detail=str(error))
            results.append(dict(position=key_, baseline=batch["status"], spec=batch["spec"], result=result))
            save_json(output / "frozen-routes.json", results)


if __name__ == "__main__":
    main()
