"""Capture archived interaction boundaries without inferring missing actions."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
from types import FunctionType

from bridge import HERE, bind, certify, targets
from compare_frozen import entries
from replay_frozen import replay
from nosl_experience import digest, save_json


def replay_with_trace(output, versions, spec, row):
    trace = []
    stable = None
    latest = {}
    submitted = None

    class Recorder:
        def __init__(self, game):
            self.game = game

        def request(self, command, **args):
            nonlocal stable, latest, submitted
            if command == "i1_n2_step":
                obs = targets.project(latest["observation"])
                action = next(a for a in obs["actions"] if a["index"] == args["index"])
                card = obs["hand"][action["card"]] if action.get("card") is not None else None
                submitted = dict(position=args["position"], action=action, card=card,
                                 decision=obs["decision"])
            result = self.game.request(command, **args)
            if command not in ("i1_n2_reset", "i1_n2_step"):
                return result
            episode = result.get("episode",{})
            latest = episode
            if episode.get("audit_stamp") and episode["status"] == "active" and (
                    episode.get("observation") or {}).get("decision",{}).get("phase")=="combat":
                stable = episode["actions"]
            if episode.get("interaction_trace"):
                trace.append(dict(position=episode["actions"],**episode["interaction_trace"]))
            return result

        def __getattr__(self,name):
            return getattr(self.game,name)

    probe = FunctionType(replay.__code__,replay.__globals__|dict(
        open_worker=lambda *args: Recorder(targets.open_worker(*args)),certify=certify))
    result = probe(output,versions,spec,row)
    return dict(result=result,trace=trace,latest_status=latest.get("status"),
                latest_detail=latest.get("detail"),latest_boundary=(latest.get("result") or {}).get("boundary"),
                consumed_decisions=latest.get("actions",0),stable_boundary=stable,
                public_menu=bool((latest.get("observation") or {}).get("actions")),
                last_submitted=submitted,terminal_verified=bool(result.get("terminal_verified")))


def case(output, versions, item, previous):
    step,key,batch = item
    old = previous[(step,key)]
    row = next(iter(batch["rows"]),None)
    record = dict(step=step,position=key,root=digest(batch["spec"]),spec=batch["spec"],
                  previous=old,archived_actions=0 if row is None else len(row["transitions"]))
    if row is None:
        return record | dict(category="engine_failure")
    if not row["transitions"]:
        return record | dict(category="incomplete_archived_route")
    try:
        data = replay_with_trace(output,versions,batch["spec"],row)
    except (targets.BANK.f1.i2.StopRun, KeyError, ValueError, RuntimeError, TypeError) as error:
        return record | dict(category="engine_failure",detail=str(error)[:400])
    result = data["result"]
    trace = data["trace"]
    last = trace[-1] if trace else {}
    reason = last.get("reason")
    if result.get("terminal_verified"):
        category = result["certification"]
    elif result.get("certification") in ("semantic_mismatch","semantic_native_match"):
        category = result["certification"]
    elif result["status"] == "rule_risk":
        category = "rule_risk"
    elif reason in ("visibility_unverified","ambiguous_draw_instances","checkpoint_unavailable","mod_defined_binding","request_or_spec_missing"):
        category = reason
    elif data["latest_status"] == "unsupported" and data["latest_boundary"] == "None":
        category = "solver_execution_risk"
    elif result["status"] in ("public_prefix_difference","binding_difference"):
        category = result["status"]
    elif data["latest_status"] in ("active","truncated"):
        category = "incomplete_archived_route"
    else:
        category = result.get("certification",result["status"])
    action = row["transitions"][-1]
    card = action["action"].get("card")
    return record | dict(category=category,last_archived_action=action["action"],
        last_archived_card=action["observation"]["hand"][card]["id"] if card is not None else None, **data)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("ledgers",type=Path,nargs="+")
    parser.add_argument("--solver",type=Path,required=True)
    parser.add_argument("--workers",type=int,default=6)
    a=parser.parse_args()
    output=a.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    frozen=HERE.parent/"m1-nosl3c-iif/coverage.json.gz"
    old=json.loads(gzip.decompress(frozen.read_bytes()))["rows"]
    targets.configure()
    versions=bind(output,a.solver.resolve())
    save_json(output/"engine.json",versions)
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for ledger in a.ledgers:
            previous={(r["update"],r["position"]):r for r in old[ledger.name]}
            results=[]
            for result in pool.map(lambda item:case(output,versions,item,previous),entries(ledger)):
                results.append(result)
                save_json(output/(ledger.name+".json"),results)
