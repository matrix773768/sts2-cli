"""Derive comparable process, RPC, quality and conditional production metrics; preserve all receipts."""
from collections import Counter,defaultdict
import gzip
import hashlib
import json
import zipfile
from campaign import RUNS,HERE,ROOT,ledger
from run import good,complete
from summarize import quantiles,summarize

def read(p):
    return json.loads(p.read_bytes())

def calculate(entry):
    d=RUNS/entry["tag"]
    result=read(d/"result.json")
    is_world=entry["kind"] not in ("natural","pairs")
    totals=result["totals"]
    wall=result["production_wall_s"];worker=result["production_worker_s"]
    row=dict(tag=entry["tag"],kind=entry["kind"],arm=entry["arm"],n=entry["n"],mode=entry["mode"],
        comparable=entry["success"],wall_s=wall,worker_s=worker,charged_s=entry["worker_s"],
        totals=totals,wall_rates={k:v/wall for k,v in totals.items()},worker_rates={k:v/worker for k,v in totals.items()})
    stages=Counter();host=Counter();host_ns=Counter();labels=Counter();suffix=Counter();root_stats=[]
    py_cpu=host_cpu=0;mem=[];boundaries=[];tail=[];elapsed=[];steady_valid=0;first=[];proc_spans=[]
    outcome_errors=Counter();quality=Counter();resource=Counter()
    compressed_bytes=0
    for wdir in sorted(d.glob("worker-*")):
        meta=read(wdir/"worker.json");proc=read(wdir/"process.json")
        py_cpu+=meta["python_cpu_ns"]/1e9
        host_cpu+=sum(h["cpu_s"] for h in meta["host_resources"])
        mem.append(dict(python_peak=meta["python_resources"]["peak_rss"],host_peak=max(
            (h["peak_rss"] for h in meta["host_resources"]),default=0),processes=len(meta["host_resources"])))
        compressed_bytes+=meta["closed"]["bytes"]
        for key in ("read_bytes","write_bytes"):
            resource["python_"+key]+=meta["python_resources"][key]
            resource["host_"+key]+=sum(h[key] for h in meta["host_resources"])
        for gen,entry_gc in enumerate(meta["gc"]):
            resource[f"python_gc_{gen}"]+=entry_gc["collections"]
        for h in meta["host"]:
            for gen,collections in enumerate(h["gc"]):resource[f"host_gc_{gen}"]+=collections
        stages.update(meta["stages"])
        for h in meta["host"]:
            for k,v in h["values"].items():
                if k.endswith("_ticks"):host_ns[k]+=v/h["frequency"]
                else:host[k]+=v
        records=list(map(json.loads,gzip.open(wdir/"evidence"/meta["closed"]["file"])))
        ends=meta["record_flushed_ns"]
        first.append((ends[0][1]-proc["start"])/1e9)
        spans=[(y[1]-x[1])/1e9 for x,y in zip(ends,ends[1:])]
        boundaries.extend(spans)
        proc_spans.append([proc["start"],proc["end"]])
        elapsed.append((meta["closed"]["at"]-proc["start"])/1e9)
        tail.append((meta["closed"]["at"]-ends[-1][1])/1e9)
        for i,r in enumerate(records):
            if is_world:
                valid=complete(r)
                if not valid:outcome_errors[r.get("error") or ("unmatched_or_partial" if r["worlds"] else "no_eligible_root")]+=1
                for w in r["worlds"]:
                    for o in w["outcomes"]:labels[o.get("status","missing")]+=1
            elif entry["kind"]=="natural":
                valid=bool(r.get("terminal"));labels[r["status"]]+=1
                for q in r["queries"]:
                    for k in ("calls","attempted_policies","full_policies","used","policy_requests","policy_calls"):
                        quality[k]+=q.get(k,0)
            else:
                valid=good(r) if "outcomes" in r else False
                if not valid:outcome_errors[r.get("error") or r.get("skip") or "unmatched_or_partial"]+=1
            if i:steady_valid+=valid
        if (wdir/"world-stages.json").exists():
            lookup={r["i"]:r for r in records}
            for r in read(wdir/"world-stages.json"):
                sample=lookup[r["i"]];parts=r["sides"]
                outcome_by_side={(j,k):o for j,w in enumerate(sample["worlds"]) for k,o in enumerate(w["outcomes"])}
                per_world=Counter()
                for p in parts:
                    key=(p["world"],p["side"]);o=outcome_by_side.get(key,{})
                    per_world[key[0]]+=p["elapsed_ns"]/1e9
                    suffix["attempted_sides"]+=1
                    suffix["execute_n"]+=p["delta"].get("conditions/initial_execute/n",0)
                    suffix["fight_n"]+=p.get("suffix_started",False)
                    suffix["returned_fight_n"]+=int("suffix_status" in p)
                    suffix["nonempty_fight_n"]+=int(p.get("suffix_decisions",0)>0)
                    if "suffix_inference" in p:
                        suffix["inference_sampled_fights"]+=1
                        for key,value in p["suffix_inference"].items():
                            suffix["suffix_"+key.replace("/ns","/s")]+=value/1e9 if key.endswith("/ns") else value
                    suffix["matched_terminal"]+=bool(o.get("matched") and o.get("utility") is not None)
                    for k in ("prefix_actions","suffix_decisions","suffix_queries","suffix_sim_calls","suffix_turns","shuffle_sent","shuffle_received","shuffle_calls"):
                        suffix[k]+=p.get(k,0)
                    for k in ("shuffle","verify","suffix_wall","elapsed"):suffix[k+"_s"]+=p.get(k+"_ns",0)/1e9
                    if p["side"]==1:suffix["second_shuffle_s"]+=p.get("shuffle_ns",0)/1e9
                    for k in ("pairs/restore","restore/replayed_action","world/start","conditions/initial_execute","lane/reset","G2/forward","V2/forward"):
                        suffix[k+"_s"]+=p["delta"].get(k+"/ns",0)/1e9
                    suffix["side_root_creates"]+=p["delta"].get("world/start/n",0)
                root_stats.append(dict(i=r["i"],count=sample.get("world_count",0),valid=complete(sample),
                    worlds=len(sample["worlds"]),fixed_s=r["fixed_ns"]/1e9,total_s=r["root_ns"]/1e9,
                    fixed_restore_n=r["fixed_counts"].get("pairs/restore/n",0),
                    fixed_pair_s=r["fixed_counts"].get("conditions/pair/ns",0)/1e9,
                    fixed_compile_s=r["fixed_counts"].get("option/program/ns",0)/1e9,
                    fixed_menu_s=r["fixed_counts"].get("conditions/menu/ns",0)/1e9,
                    world_s=list(per_world.values())))
    row.update(python_cpu_s=py_cpu,host_cpu_s=host_cpu,memory=mem,worker_spans_s=elapsed,first_s=first,
        after_last_flush_s=tail,inter_record_s=quantiles(boundaries),steady_valid_per_worker_s=steady_valid/sum(boundaries) if boundaries else None,
        peak_workers=max(sum(x<=a<y for x,y in proc_spans) for a,b in proc_spans),labels=labels,quality=quality,failures=outcome_errors)
    row.update(compressed_bytes=compressed_bytes,resource_totals=resource)
    if is_world:
        row.update(roots=root_stats,marginal=suffix,s_per_valid_root=worker/totals["valid"] if totals["valid"] else None,
            s_per_admitted_world=worker/totals["admitted_worlds"] if totals["admitted_worlds"] else None)
    else:row["strata"]=summarize(d)["strata"]
    if stages:
        row["raw_bytes"]=stages["storage/raw_bytes"]
        row["exclusive_uncovered_s"]=entry["worker_s"]-sum(v/1e9 for k,v in stages.items() if k.endswith("/self_ns"))
        rpc=Counter()
        for k,v in stages.items():
            if k.startswith("rpc/") and k.endswith("/ns"):rpc[k.split("/")[1]]+=v/1e9
        by_rpc={}
        for cmd,sec in rpc.items():
            parts=dict(python_json=sum(stages.get(f"rpc_json/{di}/{cmd}/ns",0) for di in ("send","recv"))/1e9,
                parse=host_ns[cmd+"/parse_ticks"],handle=host_ns[cmd+"/handle_ticks"],serialize=host_ns[cmd+"/serialize_ticks"])
            by_rpc[cmd]=dict(wait_s=sec,residual_s=sec-sum(parts.values()),**parts)
        row["rpc"]=by_rpc
        row["inclusive_s"]={k[:-3]:v/1e9 for k,v in stages.items() if k.endswith("/ns") and not k.startswith("host_probe/")}
        row["cache"]={k:v for k,v in stages.items() if any(s in k for s in ("prior_cache_hits","cache_hits_including_batch","forward_inputs","/batch/","parents/files","parents/rows"))}
        row["prefix"]=dict(hit_lengths={k.split("/")[-1]:v for k,v in host.items() if "/prefix_hit_length/" in k},
            replay_steps=sum(v for k,v in host.items() if k.endswith(("/replay_action","/replay_choice"))),
            evictions=sum(v for k,v in host.items() if k.endswith("/evictions")),
            fork_copy_s=sum(v for k,v in host_ns.items() if k.endswith(("/fork_ticks","/cache_fork_ticks","/belief_fork_ticks"))),
            ref_step_s=sum(v for k,v in host_ns.items() if "/reference_" in k and k.endswith("_ticks")),
            route_bytes_sent=stages["bytes_sent/i1_core5_reference"],response_bytes=stages["bytes_received/i1_core5_reference"])
    return row

def export():
    output=HERE/"evidence"/"formal";output.mkdir(parents=True,exist_ok=True)
    book=ledger()
    rows=[calculate(r) for r in book if "tag" in r and (RUNS/r["tag"]/"result.json").exists() and not r["smoke"]]
    (output/"summary.json").write_text(json.dumps(rows,indent=2))
    with zipfile.ZipFile(output/"production-receipts.zip","w",compression=zipfile.ZIP_DEFLATED,compresslevel=4) as z:
        for r in book:
            if "tag" not in r:continue
            folder=RUNS/r["tag"]
            for f in list(folder.glob("result.json"))+list(folder.glob("worker-*/*.json"))+list(folder.glob("worker-*/evidence/*.gz")):
                if f.name!="panel.gz":z.write(f,str(f.relative_to(RUNS)))
    (output/"campaign.json").write_text(json.dumps(book,indent=2))
    costs=Counter();family_costs=Counter();seen=set()
    for entry in book:
        kind=entry["kind"]
        family=("5D" if kind in ("natural","pairs") else "5E" if kind in ("initial-train","initial-dev","audit") else kind)
        family_costs[family]+=entry["worker_s"]
        identity=(kind,entry.get("arm"),entry.get("n"),entry.get("mode"))
        if not entry["success"]:category="failed"
        elif kind=="build" or kind=="native":category=kind
        elif entry["smoke"]:category="semantic_smoke"
        elif entry["mode"]=="diagnostic":category="diagnostic"
        elif identity in seen:category="repeat"
        elif entry["n"]>1:category="scaling"
        else:category="first_formal"
        costs[category]+=entry["worker_s"]
        if not entry.get("smoke"):seen.add(identity)
    (output/"budget.json").write_text(json.dumps(dict(charged_s=sum(costs.values()),budget_s=7200,
        by_category_s=costs,by_family_s=family_costs,failed_jobs=sum(not v["success"] for v in book)),indent=2))
    for source,name in ((RUNS/"infra0b-world-check.json","world-check.json"),(RUNS/"infra0b-budget-stop.json","budget-stop.json"),
            (ROOT/"logs/infra0-world-inputs/inputs.json","world-inputs.json"),(ROOT/"logs/infra0-world-profile/build.json","meter-host.json")):
        if source.exists():(output/name).write_bytes(source.read_bytes())
    world=read(output/"world-inputs.json")
    fixed=read(ROOT/"experiments/m1-core5c/evidence/ledger.json")
    assets={"lib/sts2.dll":fixed["game"],"experiments/m1-core5a/evidence/v2.pt":fixed["weights"]["v2"],
        "logs/inf1/jobs/dc2b-night1-hf1/g2-fit/best.pt":fixed["g2"]}
    assets.update({"experiments/"+k:v for k,v in fixed["static_rules"].items()})
    for host,ident in (("core5e-world-host",world["world_host"]),("infra0-world-profile",read(output/"meter-host.json")),
                       ("core5c-host",{"artifacts":fixed["host"]}),("infra0-profile-host",read(ROOT/"logs/infra0-profile-host/build.json"))):
        for name,digest in ident["artifacts"].items():assets[f"logs/{host}/{name}"]=digest
    from infra_assets import sha
    for name,digest in assets.items():
        if sha(ROOT/name)!=digest:raise ValueError("Asset changed: "+name)
    code={}
    for root in (ROOT/"experiments/m1-core5e",HERE):
        for path in sorted(root.glob("*.py")):
            code[path.relative_to(ROOT).as_posix()]=hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()
    manifest=dict(core5d="5bb7c68bbb66e25b419460743d09f74568ca3372",core5e=world["commit"],
        parent_infra="cd011d0179638ffecb5cf37440ac04df41fc6811",runtime_sha256=assets,source_sha256_lf=code,
        first_pass_world_meter_sha256_lf="a62122d09f119d7644db6d0907a411fef9447701e5187c2826705d50c73351d3",
        panel_sha256={p:sha(HERE/p) for p in ("panel.json","world-panel.json")})
    (output/"deployment.json").write_text(json.dumps(manifest,indent=2))
    return rows
if __name__=="__main__":export()
