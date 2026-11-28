"""Publish actual public observations from committed workers for future G2 re-encoding."""
import argparse
import gzip
import json
import os
from pathlib import Path
import tempfile
from experience import digest,read_rows,require,sha
from produce_batch import exclusive,write

def actions(row):
    choices={}
    for c in row["choices"]:choices.setdefault(c["at"],[]).append(c["selected"])
    return [index for i,t in enumerate(row["trace"]) for index in [t[1],*choices.get(i,[])]]

def public(reply):
    return {k:reply[k] for k in ("status","view","facts","kind","options") if k in reply}

def project(attempt,rows):
    by_seed={r["seed"]:r for r in rows}
    results={}
    for file in sorted((attempt/"production/transport").glob("*/commands.jsonl")):
        active=segment=state=None
        with file.open("rb") as commands,(file.parent/"stdout.log").open("rb") as replies:
            requests=(c for c in map(json.loads,commands) if c["op"]!="g2")
            answers=(line for line in replies if line.startswith(b'{"type":"hot"'))
            for cmd,line in zip(requests,answers):
                op=cmd["op"]
                if op not in ("open","step","restore"):continue
                answer=json.loads(line);after=answer.get("result")
                if op=="open":
                    seed=cmd["spec"]["seed"];task=by_seed[seed]
                    require(task["spec"]==cmd["spec"] and seed not in results,"ambiguous opening")
                    active=results[seed]=dict(task_id=task["task_id"],segments=[])
                if op in ("open","restore"):
                    segment=dict(origin=op,world=cmd.get("world"),steps=[])
                    # Audit perturbations and unused restores are not actual decisions.
                    state=after
                    if op=="open":active["segments"].append(segment)
                    continue
                require(active is not None and isinstance(state,dict),"missing prior decision")
                if segment["origin"]=="restore" and not segment["steps"]:active["segments"].append(segment)
                segment["steps"].append(dict(index=cmd["index"],observation=public(state)))
                if not answer["ok"]:segment["error"]=answer.get("reason")
                elif after["status"] in ("Victory","Defeat"):segment["terminal"]=public(after)
                state=after
    require(set(results)==set(by_seed),"missing transport records")
    for row in rows:
        output=results[row["seed"]]
        if row["eligible"]:
            r=row["trajectory"]
            expected=[r] if row["kind"]=="natural" else [r["prefix"],*[s["trajectory"] for pair in [r["natural_pair"],*[w["outcomes"] for w in r["worlds"]]] for s in pair]]
            for seg,w in zip(output["segments"],expected,strict=True):
                require([s["index"] for s in seg["steps"]]==actions(w),"public trace action mismatch")
                if w.get("terminal"):
                    t=seg["terminal"]
                    require(t["status"]==w["status"] and all(t["facts"][k]==w["terminal"][k] for k in ("hp","max_hp","gold")),"public trace terminal mismatch")
        yield output

def publish(data,work):
    manifest=json.loads((data/"manifest.json").read_bytes())
    require(digest({k:v for k,v in manifest.items() if k!="id"})==manifest["id"],"unsealed dataset")
    folder=data/"public";folder.mkdir(exist_ok=True)
    with exclusive(data/"writer.lock"),tempfile.TemporaryDirectory(dir=folder) as tmp:
        files={}
        for shard in manifest["shards"]:
            name=shard["shard"];src=data/shard["file"]
            require(sha(src)==shard["sha256"],"source shard changed")
            dirs=[p.parent for p in (work/name).glob("*/finished.json")]
            # A coordinator may have died after rename but before writing the local receipt.
            if not dirs:dirs=[p.parent.parent for p in (work/name).glob("*/production/ledger.json")
                              if json.loads(p.read_bytes())==shard["ledger"]]
            require(len(dirs)==1,"ambiguous committed worker")
            dest=folder/(name+".gz");temp=Path(tmp)/dest.name
            with temp.open("xb") as f,gzip.GzipFile(fileobj=f,mode="wb",filename="",mtime=0) as z:
                for record in project(dirs[0],list(read_rows(src))):
                    z.write(json.dumps(record,separators=(",",":"),allow_nan=False).encode()+b"\n")
            h=sha(temp)
            if dest.exists():require(sha(dest)==h,"existing public shard differs")
            else:os.replace(temp,dest)
            files[name]=h
        index=dict(dataset=manifest["id"],files=files);index["id"]=digest(index)
        path=folder/"index.json"
        if path.exists():require(json.loads(path.read_bytes())==index,"different observation manifest")
        else:write(path,index)
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("data",type=Path);p.add_argument("work",type=Path)
    a=p.parse_args();publish(a.data,a.work)
