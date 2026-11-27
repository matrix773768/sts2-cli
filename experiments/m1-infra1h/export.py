"""Export complete raw rows, resource receipts and independent, ordered 0B comparisons."""
import collections
import gzip
import hashlib
import json
from pathlib import Path
import zipfile
import sys
from campaign import BOOK,E,HERE,OLD,ROOT,RUNS,sha

def canonical(row):
    row=dict(row);row.pop("seconds",None)
    return hashlib.sha256(json.dumps(row,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def oracle():
    base={}
    with zipfile.ZipFile(OLD/"evidence/formal/production-receipts.zip") as z:
        for r in json.loads((OLD/"evidence/formal/campaign.json").read_bytes()):
            k=r.get("kind")
            if k in base or r.get("mode")!="baseline" or r["arm"]!="V2" or r["smoke"] or r["n"]!=1:continue
            d=r["tag"]+"/worker-0/"
            w=json.loads(z.read(d+"worker.json"))
            records=map(json.loads,gzip.decompress(z.read(d+"evidence/"+w["closed"]["file"])).splitlines())
            base[k]={str(a["i"]):canonical(a) for a in records}
            assert base[k]==r["semantics"]
    return base

def verify():
    expected=oracle()
    table=json.loads((E/"runs.json").read_bytes())
    with zipfile.ZipFile(E/"production.zip") as z:
        if z.testzip():raise ValueError("CRC")
        root_trace=json.loads(z.read("infra1h-pre-natural-original/worker-0/semantic.json"))
        with zipfile.ZipFile(OLD/"evidence/formal/production-receipts.zip") as frozen:
            world_trace=json.loads(frozen.read("infra0b-005-initial-train-baseline/worker-0/semantic.json"))
        for r in table:
            d=r["label"]+"/worker-0/"
            meta=json.loads(z.read(d+"worker.json"))
            raw=z.read(d+"evidence/"+meta["closed"]["file"])
            result=json.loads(z.read(r["label"]+"/result.json"))
            assert hashlib.sha256(raw).hexdigest()==result["workers"][0]["file_sha256"]
            records=list(map(json.loads,gzip.decompress(raw).splitlines()))
            base=expected[r["kind"]]
            diff={str(a["i"]):canonical(a) for a in records if canonical(a)!=base[str(a["i"])]}
            assert (not diff)==r["matches"]
            assigned=result["workers"][0]["ids"]
            actual=[str(a["i"]) for a in records]
            assert sorted(map(int,actual))==sorted(assigned)
            if r.get("sample"):
                n=r["sample"];ids=sorted(base,key=int) if r["kind"] in ("pairs","natural") else list(base)
                assert list(map(str,assigned))==[ids[j*(len(ids)-1)//(n-1)] for j in range(n)]
                assert actual==[idx for idx in base if int(idx) in assigned]
            elif not r["smoke"]:assert actual==list(base)
            assert len(records)==r["rows"]
            if r["matches"] and r["smoke"] and r["label"].startswith("infra1h-pre-"):
                expected_trace=root_trace if r["kind"]=="natural" else world_trace
                assert json.loads(z.read(d+"semantic.json"))==expected_trace,(r["label"],"public trace")
            if r["matches"] and "fair" in r.get("models",{}):
                sample=r["models"]["fair"]
                assert len(sample)==3 and all(v==sample[0] for v in sample)
    book=json.loads((E/"campaign.json").read_bytes())
    assert abs(book["worker_seconds"]-sum(a["seconds"] for a in book["attempts"]))<1e-6 and book["worker_seconds"]<=7200
    for stream in E.glob("c-model*.json.gz"):
        diag=json.load(gzip.open(stream));audit=diag["rows"]
        assert len(audit)==diag["stats"]["compared"]+sum(diag["abstained"].values())
        assert sum(row.get("equal",False) for row in audit)==diag["stats"].get("exact_tensor",0)
        for row in audit:
            if row.get("reason") is None:assert (row["reference"]==row["candidate"])==row["equal"]
    if (E/"native-natural.json").exists():
        for r in json.loads((E/"native-natural.json").read_bytes())["rows"]:
            if r["matched"]:
                assert r["actual"]["hp"]==r["expected"]["hp"]
                assert r["native_max_hp"]==r["expected"]["max_hp"] and r["native_gold"]==r["expected"]["gold"]
    print("verified",len(table),"runs",sum(r["rows"] for r in table),"records")

def export():
    book=[json.loads(x) for x in BOOK.read_text().splitlines()]
    budget=sum(x["seconds"] for x in book)
    if budget>7200:raise ValueError("Budget exceeded")
    rows=[]
    incomplete=[]
    from build import source_manifest
    hosts={"hot-k2":json.loads((ROOT/"logs/infra1h-hot-k2/manifest.json").read_bytes())}
    for p in sorted((ROOT/"logs").glob("infra1h-5*")):
        if (p/"build.json").exists():
            manifest=json.loads((p/"build.json").read_bytes())
            for file,digest in manifest["artifacts"].items():assert sha(p/file)==digest
            hosts[p.name]=dict(artifacts=manifest["artifacts"],parent=manifest["infra1h_parent"])
            hosts[p.name]["sources"]=source_manifest(p/"host/Headless")
            if (p/"hot.json").exists():
                hot=json.loads((p/"hot.json").read_bytes())
                dll=p/"host/Headless/bin/Debug/net9.0/hot"
                assert sha(dll/"OfflineSearchHarness.dll")==hot["adapter"] and sha(dll/"CombatSolver.dll")==hot["hot_solver"]
                hosts[p.name]["hot"]=hot
                hosts[p.name]["adapter_sources"]={f.name:sha(f) for f in sorted((p/"plugin").glob("*.cs"))}
    for family in ("5d","5e"):
        hosts["parent-"+family]=source_manifest(ROOT/"logs"/("infra1a-"+family+"-batch")/"host/Headless")
    E.mkdir(exist_ok=True)
    with zipfile.ZipFile(E/"production.zip","w",zipfile.ZIP_DEFLATED,compresslevel=4) as z:
        for entry in book:
            tag=entry["label"];d=RUNS/tag;w=d/"worker-0"
            log=BOOK.parent/(tag+".log")
            if log.exists():z.write(log,"attempts/"+log.name)
            if not (d/"result.json").exists():
                for p in [*w.glob("*.json"),*w.glob("worker.log"),*w.rglob("failure.txt"),*[f for f in (w/"evidence").glob("*.gz") if f.name!="panel.gz"]]:
                    z.write(p,p.relative_to(RUNS))
                if (w/"task.json").exists():
                    task=json.loads((w/"task.json").read_bytes())
                    gold=oracle()[task["kind"]]
                    for partial in (w/"evidence").glob("*.gz"):
                        if partial.name=="panel.gz":continue
                        ids=[];different=[]
                        try:
                            with gzip.open(partial) as chunk:
                                for line in chunk:
                                    row=json.loads(line);idx=str(row["i"]);ids.append(row["i"])
                                    if canonical(row)!=gold[idx]:different.append(row["i"])
                        except (EOFError,OSError,ValueError):pass
                        incomplete.append(dict(label=tag,ids=ids,different=different,assigned=task["ids"],closed=False))
                continue
            result=json.loads((d/"result.json").read_bytes());meta=json.loads((w/"worker.json").read_bytes())
            check=json.loads((w/"verification.json").read_bytes())
            info=result["treatment"]
            counts=collections.Counter();reasons=collections.Counter();gc=[0,0,0];private=[];timers=collections.Counter()
            candidates=list(w.glob("*.json"))+[d/"result.json",w/"evidence"/meta["closed"]["file"]]
            for p in w.rglob("infra1h-engine.json"):
                h=json.loads(p.read_bytes());reasons.update(h.pop("Reasons"));g=h.pop("gc")
                for i,num in enumerate(g):gc[i]+=num
                counts.update(h);candidates.append(p)
            for p in w.rglob("infra1h-timers.json"):
                t=json.loads(p.read_bytes());freq=t.pop("frequency");timers.update({k:v/freq for k,v in t.items()});candidates.append(p)
            for p in w.rglob("infra1h-private.jsonl"):
                private.extend(json.loads(x) for x in p.read_text().splitlines());candidates.append(p)
            for p in w.rglob("failure.txt"):candidates.append(p)
            for p in candidates:z.write(p,p.relative_to(RUNS))
            models={}
            for p in w.glob("infra1h-*.json"):
                models[p.stem.removeprefix("infra1h-")]=json.loads(p.read_bytes())
            stats=meta["stages"]
            by_root={}
            prev=meta["entry_ns"]
            for i,t in meta["record_flushed_ns"]:
                by_root[i]=(t-prev)/1e9;prev=t
            rows.append(dict(label=tag,kind=info["kind"],variant=info["variant"] or "original",smoke=info["smoke"],mode=info["mode"],sample=info.get("sample"),
                wall=result["production_wall_s"],charged=entry["seconds"],worker=result["process_worker_s"],
                python_cpu=meta["python_cpu_ns"]/1e9,host_cpu=sum(x["cpu_s"] for x in meta["host_resources"]),
                python_mib=meta["python_resources"]["peak_rss"]/2**20,host_mib=max((x["peak_rss"] for x in meta["host_resources"]),default=0)/2**20,
                totals=result["totals"],rates=result["per_wall_second"],matches=check["equal"],rows=check["rows"],counts=counts,reasons=reasons,
                host_gc=gc,python_gc=[v["collections"] for v in meta["gc"]],by_root_s=by_root,
                import_s=(meta["imported_ns"]-meta["entry_ns"])/1e9,private=private,
                models=models,timers=timers,stages={k:v for k,v in stats.items() if k.startswith(("bytes_sent/","bytes_received/","G2/forward","V2/forward","rpc/","rpc_json/","model/load","world/start","project/","world_host/project/","host_probe/pre0_start/","turn/search","plan/__call__")) and "/prefix/" not in k}))
    starts=[b.get("start_utc_unix",(BOOK.parent/(b["label"]+".log")).stat().st_ctime) for b in book]
    span=max(t+b["seconds"] for t,b in zip(starts,book))-min(starts)
    for target,data in (("campaign",dict(worker_seconds=budget,experiment_elapsed_s=span,incomplete=incomplete,attempts=book)),("hosts",hosts),("runs",rows)):
        (E/(target+".json")).write_text(json.dumps(data,indent=2),encoding="utf8")
    verify()
if __name__=="__main__":
    if "--verify" in sys.argv:verify()
    else:export()
