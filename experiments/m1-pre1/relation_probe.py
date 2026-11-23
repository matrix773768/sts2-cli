"""Check scoped order labels against two frozen-Solver local transitions."""
import argparse
from contextlib import ExitStack, closing
import gzip
import json
from pathlib import Path
import sqlite3

from evaluate import bind
from labels import scoped_order


def action_key(obs, action):
    card = next(c for c in obs["hand"] if c["index"] == action["card"])
    return card["id"], card["upgrade"], action["target"]


def branch(output, runtime, versions, spec, keys):
    with ExitStack() as stack:
        game = runtime["targets"].open_worker(output, stack, versions)
        state = game.request("pre0_start",spec=spec,cap=8)["episode"]
        for expected in keys:
            if state["status"] != "active":
                break
            obs = runtime["targets"].project(state["observation"])
            action = next(a for a in obs["actions"] if a["kind"] == "play_card"
                          and action_key(obs,a)==expected)
            state = game.request("i1_n2_step",position=state["actions"],index=action["index"])["episode"]
        if state["status"] == "predicted_win":
            return state["actions"], 0, state["status"]
        if state["status"] != "active":
            raise ValueError(f"Local relation witness did not reach a public boundary: {state['status']}")
        view = runtime["targets"].project(state["observation"])
        return state["actions"], sum(e["hp"] for e in view["enemies"]), state["status"]


def verify(source, output, host, count):
    output.mkdir()
    runtime, versions = bind(output,host)
    results = []
    with closing(sqlite3.connect(source.resolve().as_uri()+"?mode=ro",uri=True,timeout=30)) as db:
        candidates = db.execute("""
            SELECT payload, recipe FROM trajectories JOIN private_tasks USING(id)
            WHERE complete=1 AND split='train' ORDER BY ordinal LIMIT 3000
        """).fetchall()
    for payload, recipe in candidates:
        row = json.loads(gzip.decompress(payload))
        obs = row["steps"][0]["observation"]
        order = scoped_order(obs)
        if order is None:
            continue
        keys = [action_key(obs,obs["actions"][index]) for index in order]
        spec = json.loads(recipe)
        forward = branch(output,runtime,versions,spec,keys)
        reverse = branch(output,runtime,versions,spec,keys[::-1])
        matched = forward[1] < reverse[1] or (forward[2]==reverse[2]=="predicted_win" and forward[0]<reverse[0])
        results.append(dict(id=row["id"], card_ids=[key[0] for key in keys], expected=list(order),
                            forward=forward, reverse=reverse, match=matched))
        if len(results) == count:
            break
    (output/"witnesses.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    if len(results) != count or any(not r["match"] for r in results):
        raise ValueError("Scoped order witnesses incomplete or divergent")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--host",type=Path,required=True)
    parser.add_argument("--count",type=int,default=8)
    args = parser.parse_args()
    print(json.dumps(verify(args.dataset,args.output,args.host,args.count),indent=2))
