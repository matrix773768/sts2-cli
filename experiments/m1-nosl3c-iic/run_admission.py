"""Collect every planned attempt and optimize only independently certified v3 routes."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from types import FunctionType

import torch

from admission import HERE, VERSION, admitted, certify, digest
from engine import BANK, CAPTURE, bind, open_worker
from nosl_experience import save_json, terminal
from roots import generate
from train_interactive import Journal, Policy, checkpoint_policy, collect, optimize

FAILURES = (BANK.f1.i2.StopRun, ValueError, RuntimeError, KeyError, OSError, TimeoutError)


def attempt(output, versions, spec, policy, model_hash, seed, cap):
    started = perf_counter()
    constructed = False
    stop_detail = None

    def capture(game, root):
        nonlocal constructed
        result = CAPTURE(game, root)
        constructed = True
        return result

    def terminal_with_diagnostic(state, last_action):
        nonlocal stop_detail
        stop_detail = state.get("detail")
        return terminal(state, last_action)

    try:
        collector = collect.__wrapped__
        worker = FunctionType(collector.__code__, collector.__globals__ | {"CAPTURE": capture, "terminal": terminal_with_diagnostic})
        with torch.no_grad():
            result = worker(output, versions, spec, policy, model_hash, seed, cap)
    except FAILURES as error:
        return dict(status="engine_failure" if constructed else "root_failure",
                    constructed=constructed, timing=dict(total_ms=(perf_counter()-started)*1000),
                    rows=[], evidence=dict(terminal_verified=False, detail=str(error)))
    row, = result["rows"]
    audit_started = perf_counter()
    try:
        evidence = certify(output, versions, spec, row)
    except FAILURES as error:
        evidence = dict(status="audit_failure", terminal_verified=False, detail=str(error))
    if stop_detail is not None:
        evidence["prediction_stop_detail"] = stop_detail
    row["feedback"]["eligible"] = admitted(row, evidence)
    row["feedback"]["evidence"] = "exact_native_route" if row["feedback"]["eligible"] else "unqualified"
    result["timing"]["audit_ms"] = (perf_counter()-audit_started)*1000
    result["timing"]["total_ms"] = (perf_counter()-started)*1000
    return result | dict(status=evidence["status"], constructed=True, evidence=evidence)


def summarize(output, batches, update, elapsed, stats):
    statuses = Counter(b["status"] for b in batches)
    mechanisms = Counter()
    groups = {}
    for batch in batches:
        spec = batch["spec"]
        for value in (spec["character"], spec["encounter"]):
            groups.setdefault(value, Counter())[batch["status"]] += 1
        for card in {c["id"] for c in spec["deck"]}:
            mechanisms[card, batch["status"]] += 1
    predictions = Counter(row["feedback"]["status"] for b in batches for row in b["rows"])
    summary = dict(update=update, attempted=len(batches), constructed=sum(b["constructed"] for b in batches),
                   completed=predictions["predicted_win"]+predictions["death"]+predictions["rule_risk"],
                   predictions=predictions, admissions=statuses, by_group=groups,
                   by_deck_card=[dict(card=c, status=s, attempts=n) for (c,s),n in sorted(mechanisms.items())],
                   seconds=elapsed, attempts_per_second=len(batches)/elapsed if elapsed else 0,
                   audit_worker_seconds=sum(b["timing"].get("audit_ms",0)/1000 for b in batches), optimizer=stats)
    save_json(output / "report.json", summary)
    lines = ["# NOSL v3 规则资格", "", f"尝试 {len(batches)} 条，准入 "
             f"{sum(n for s,n in statuses.items() if s.startswith('admissible_'))} 条", ""]
    lines.extend(f"- {s} {n}" for s,n in sorted(statuses.items()))
    (output / "report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def run(output, solver, config, workers, through):
    versions = bind(output, solver)
    dependencies = [
        "m1-nosl3c-iib/engine.py", "m1-nosl3c-iib/interactive_contract.py",
        "m1-nosl3c-iib/qualify_native.py", "m1-nosl3c-iib/train_interactive.py",
        "m1-nosl3c-iia/contract.py", "m1-nosl3c/learning.py", "m1-nosl3c/journal.py",
        "m1-nosl3a/nosl_model.py", "m1-nosl3a/nosl_experience.py",
        "m1-nosl3b/nosl3b_store.py",
    ]
    sources = [HERE / f for f in ("admission.py", "roots.py", "run_admission.py")]
    sources.extend(HERE.parent / f for f in dependencies)
    identity = dict(protocol=VERSION, engine=versions, config=digest(config), torch=str(torch.__version__),
                    source={p.relative_to(HERE.parent).as_posix(): sha256(p.read_bytes()).hexdigest()
                            for p in sources})
    if "random" in config:
        with ExitStack() as stack:
            catalog = open_worker(output, stack, versions).request("synthetic_catalog")
        roots = list(generate(catalog, **config["random"]))
        batches = [[r["spec"] for r in roots]]
        save_json(output / "generated.json", roots)
        identity["generated"] = digest(roots)
    else:
        batches = config["batches"]
    if not 0 <= through <= len(batches) or workers < 1:
        raise ValueError("Invalid run bounds")
    if any(not batch or any(s["schema"] != 3 or s["relics"] or any(s["potions"]) for s in batch)
           for batch in batches):
        raise ValueError("Expected resource-free schema-3 roots")
    audit = output / "audit"
    audit.mkdir(exist_ok=True)
    torch.manual_seed(config["initialization_seed"])
    policy = Policy().eval()
    adam = torch.optim.Adam(policy.parameters(), lr=config["learning_rate"])
    with BANK.writer(output), closing(Journal(output/"training.sqlite", identity)) as journal:
        def save(step, stats):
            journal.save(step, dict(model=policy.state_dict(), adam=adam.state_dict(),
                                    rng=torch.get_rng_state(), model_sha256=digest(checkpoint_policy(policy))), stats)
        step = journal.latest()
        if step is None:
            step = 0
            save(step,{})
        saved, _ = journal.load(step)
        policy.load_state_dict(saved["model"])
        adam.load_state_dict(saved["adam"])
        torch.set_rng_state(saved["rng"])
        if digest(checkpoint_policy(policy)) != saved["model_sha256"]:
            raise ValueError("Model checkpoint mismatch")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while step < through and not (output/"STOP").exists():
                started = perf_counter()
                model_hash = digest(checkpoint_policy(policy))
                done = journal.done("train",step)
                for start in range(0,len(batches[step]),workers):
                    if (output/"STOP").exists():
                        return
                    pending = []
                    for i in range(start,min(start+workers,len(batches[step]))):
                        key = f"{i:06d}"
                        if key in done:
                            continue
                        spec = batches[step][i]
                        seed = int(digest([config["policy_seed"],step,i])[:16],16)
                        future = pool.submit(attempt,output,versions,spec,policy,model_hash,seed,config["action_cap"])
                        pending.append((key,spec,future))
                    for key,spec,future in pending:
                        result = future.result()
                        evidence = result.pop("evidence")
                        evidence_file = audit/f"{step:06d}-{key}.json"
                        save_json(evidence_file,evidence)
                        journal.commit_root("train",step,result | dict(root=key,spec=spec,evidence_sha256=digest(evidence)))
                if (output/"STOP").exists():
                    return
                completed = list(journal.batches("train",step))
                for batch in completed:
                    evidence = json.loads((audit/f"{step:06d}-{batch['root']}.json").read_bytes())
                    if digest(evidence) != batch["evidence_sha256"]:
                        raise ValueError("Audit ledger checksum mismatch")
                rows = [row for b in completed for row in b["rows"] if row["feedback"]["eligible"]]
                stats = optimize(policy,adam,rows,config,model_hash) if rows and not config.get("audit_only") else {}
                summarize(output,completed,step+1,perf_counter()-started,stats)
                if not rows and not config.get("audit_only"):
                    return
                step += 1
                save(step,stats)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--solver",type=Path,required=True)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--workers",type=int,default=2)
    parser.add_argument("--through-update",type=int)
    a=parser.parse_args()
    config=json.loads(a.config.read_bytes())
    a.output.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    through=a.through_update if a.through_update is not None else len(config.get("batches",[None]))
    run(a.output.resolve(),a.solver.resolve(),config,a.workers,through)
