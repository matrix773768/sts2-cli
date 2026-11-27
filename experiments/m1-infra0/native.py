"""Map-save reload probe on the regular native harness. Keep it outside prediction throughput."""
import gzip
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from infra_assets import ROOT, sha

def probe(folder):
    folder.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(ROOT/"python"))
    import engine_client
    binary=ROOT/"logs/iik5-main-host/bin/Debug/net9.0"
    for name,expected in {"Sts2Headless.dll":"44ae4ef8309691310038a0a3f5199386e34c984198dfeda4e0f5f997161b0259",
        "GodotSharp.dll":"66cea26b3cfb7d5c4047f0b3b10e49f5ec111753cdf88475305c9ee63266e5ff"}.items():
        if sha(binary/name)!=expected:raise ValueError(f"Native host changed: {name}")
    engine_client.headless_command=lambda:[str(ROOT/"logs/m0-v5/dotnet9/dotnet.exe"),"exec","--fx-version","9.0.7",str(binary/"Sts2Headless.dll")]
    os.environ["STS2_DOTNET_VERSION"]="9.0.7"
    evidence=ROOT/"experiments/m1-core5d/evidence"
    index=json.loads((evidence/"relic-panel.json").read_bytes())
    rows={r["key"]:r for r in index["roots"]}
    results=[]
    for case in json.loads(Path(__file__).with_name("panel.json").read_bytes())["native"]:
        start=perf_counter()
        root=rows[case["key"]]
        src=json.load(gzip.open(evidence/root["file"]))
        frozen=src["roots"][root["index"]]
        client=engine_client.EngineClient(log_root=folder)
        try:
            state=client.send(dict(cmd="load_save",json=json.dumps(frozen["save"])))
            for cmd in src["commands"][root["enter"]:root["at"]+1]:state=client.send(cmd)
            ok=state.get("decision")=="combat_play" and state["enemies"]==frozen["enemies"] and all(
                state["player"][k]==frozen[k] for k in ("hp","max_hp","gold","deck","relics","potions"))
            results.append(dict(key=root["key"],act=root["act"],matched=ok,relics=root["relics"],
                prediction_admission="unsupported_native_save_import",commands=2+root["at"]-root["enter"]))
        finally:client.close()
        results[-1]["seconds"]=perf_counter()-start
    (folder/"native.json").write_text(json.dumps(results,indent=2))
    if not all(r["matched"] for r in results):raise ValueError("Native reload mismatch")

if __name__=="__main__":
    import re
    if not re.fullmatch("[a-zA-Z0-9_-]+",sys.argv[1]):raise ValueError("Invalid run tag")
    probe(ROOT/"logs/infra0-runs"/sys.argv[1])
