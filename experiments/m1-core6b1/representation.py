"""Compare actual frozen input tensors under one public-field edit. No refitting or synthetic labels."""
import copy, hashlib, time
from diagnose import *
from policy6 import encode as guide_encode
from semantic import static_rules,CARDS

def fingerprint(value):
    h=hashlib.sha256()
    def add(x):
        if isinstance(x,dict):
            for k,v in sorted(x.items()):h.update(k.encode());add(v)
        elif isinstance(x,(tuple,list)):
            for v in x:add(v)
        else:
            a=np.asarray(x);h.update(str((str(a.dtype),a.shape)).encode());h.update(a.tobytes())
    add(value);return h.hexdigest()

def variant(f,key):
    x=copy.deepcopy(f)
    if key=="phase":
        for e in x["known_enemies"]:
            if e.get("phase"):e["phase"]["committed_moves"]=[];e["phase"]["registers"]={}
            e["move"]=None
        for e in x["enemies"]:e["move"]=None
    elif key=="attack":
        for e in x["enemies"]:e["attack_hits"]=[99]
    elif key=="belief":
        x["belief"]=dict(counts={},top=[],bottom=[],shuffles=0)
    elif key=="layers":
        for c in x["hand"]:c["cost_layers"]={}
    elif key=="cost":
        if x["hand"]:x["hand"][0]["cost"]+=1
    elif key=="imbalanced":
        for e in x["enemies"]:e["powers"]=[p for p in e["powers"] if p["id"]!="IMBALANCED_POWER"]
    return x

def main():
    tick=time.perf_counter();m=s.Actor("v2")
    roots=read(E/"panel.json")["roots"]; pre=gz(E/"prefixes.gz");result={}
    rule=static_rules()
    for r in roots:
        k=r["id"];p=pre[k]; f=p["root"]["facts"];mem=m.g2.encoder.initial_history()
        for step in p["steps"]:
            obs=step["observation"]
            menu=choice_b(obs["facts"],obs) if obs["status"]=="choice" else public_b(obs["facts"])
            mem=m.advance(mem,menu,menu["actions"][step["index"]])
        def tensors(ff):
            menu=public_b(ff)
            return [fingerprint(m.g2.encoder.encode(menu,mem)),fingerprint(guide_encode(menu,mem,p["spec"]))]
        orig=tensors(f); edits={}
        for prop in ("phase","attack","belief","layers","cost","imbalanced"):
            changed=variant(f,prop)
            edits[prop]=dict(raw_changed=changed!=f,g2=tensors(changed)[0]!=orig[0],guide=tensors(changed)[1]!=orig[1])
        d=gz(E/(k+".gz"))
        states={i:v["public"] for i,v in d["states"].items()}
        if k in HUMAN:
            states.update({i:v["public"] for i,v in gz(E/(k+"-witness.gz"))["states"].items()})
        state_rows={}
        for id,c in states.items():
            gl,x=encode(c);base=fingerprint((gl,x))
            # Keep current HP, public hits and other mechanism inputs fixed in these probes.
            diff={}
            for edit in ("phase","belief","layers","imbalance_payload"):
                cc=copy.deepcopy(c)
                if edit=="phase":
                    for e in cc["enemies"]:
                        if e.get("phase"):e["phase"]["committed_moves"]=[];e["phase"]["registers"]={}
                        e["move"]=None
                elif edit=="belief":
                    cc["belief"]=dict(counts={},top=[],bottom=[],shuffles=0)
                elif edit=="layers":
                    for zone in cc["card_state"].values():
                        for card in zone:card["cost_layers"]={}
                else:
                    for e in cc["enemies"]:
                        for power in e["powers"]:
                            if power["id"]=="IMBALANCED_POWER":power["id"]="CORE_DIAGNOSTIC_UNKNOWN"
                if cc!=c:diff[edit]=fingerprint(encode(cc))!=base
            state_rows[id]=dict(features={n:int(np.count_nonzero(x[:,j])) for n,j in F.items() if x[:,j].any()},edits=diff)
        result[k]=dict(root_encoder_ids=orig,edits=edits,successors=state_rows,
            public_enemy=[dict(species=e["species"],move=e["move"],has_rule_graph=bool(rule["graphs"].get(e["species"])),phase=e.get("phase")) for e in f["known_enemies"]],
            cards=[dict(id=c["id"],frozen_rule=bool(CARDS.get(c["id"])),operations=(CARDS.get(c["id"]) or {}).get("operations",[]),cost=c["cost"],layers=c["cost_layers"]) for c in f["hand"]])
    save(E/"representation.gz",dict(roots=result,seconds=time.perf_counter()-tick))
if __name__=="__main__":main()
