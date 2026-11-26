"""Index numeric rule values by lookup key. Encoder consumes only shared rule attributes."""
from core4_roots import *
def build():
    result={}
    for source in ("n1bc-catalog","r2-rule-export"):
        for f in sorted((ROOT/"logs"/source).glob("*/export.json")):
            for r in json.loads(f.read_bytes())["result"]["input"]["cardRules"]:
                result[r["Entry"]]={k:v for k,v in r.items() if k in ("Type","Target","operations","BaseCost","UpgradedCost","BaseDamage","UpgradedDamage","BaseBlock","UpgradedBlock","BaseHits","UpgradedHits","BaseMagic","UpgradedMagic","OrderedVarNames","BaseVarValues","UpgradedVarValues")}
    with gzip.open(HERE/"cards.json.gz","wt") as f:json.dump(result,f,separators=(",",":"))
if __name__=="__main__":build()
