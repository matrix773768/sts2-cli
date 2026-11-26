"""Recover named static effects and per-edge constraints omitted in the compact N1BC view."""
import gzip
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
def compile_rules():
    result=dict(graphs={},powers={},relics={})
    for folder in ("n1bc-catalog","r2-rule-export"):
        for path in sorted((HERE.parents[1]/"logs"/folder).glob("*/export.json")):
            data=json.loads(path.read_bytes())["result"]["input"]
            for enemy in data["enemyRules"]:
                if enemy["rules"]:
                    nodes=enemy["rules"]["nodes"]
                    for n in nodes:
                        for effect in n["effects"]:effect.pop("TargetDefId",None)
                    result["graphs"][enemy["Entry"]]=nodes
            for kind in ("power","relic"):
                for item in data[kind+"Rules"]:result[kind+"s"][item["Entry"]]=item
    payload=json.loads((HERE.parents[1]/"logs/core2-powers/export/export.json").read_bytes())
    for item in payload["result"]["input"]["powerRules"]:
        result["powers"][item["Entry"]]=item
    return result
if __name__=="__main__":
    with gzip.open(HERE/"catalog.json.gz","wt",encoding="utf8") as stream:json.dump(compile_rules(),stream,separators=(",",":"))
