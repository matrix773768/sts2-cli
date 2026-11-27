"""Public move identity and inexpensive, order-invariant tactical completions."""
import gzip,json
from collections import Counter
from hashlib import sha256
from math import comb
from panel5c import HERE
from semantic import CARDS
RULE=json.load(gzip.open(HERE.parent/"m1-n1bc/catalog.json.gz"))["cards"]
def packed(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"))
def card(c):
    return {k:v for k,v in c.items() if k!="index"}
def move(h,a):
    key=dict(a)
    key.pop("index")
    if a.get("card") is not None:
        key["card"]=card(h["hand"][a["card"]])
    if a["kind"]=="select_candidate":
        key["choice"]=card(h["decision"]["candidates"][a["choice"]])
    return packed(key)
def observation(h,unordered):
    x=h.copy()
    x["actions"]=sorted(move(h,a) for a in h["actions"])
    x["discard"]=sorted(map(card,h["discard"]),key=packed)
    if unordered:
        x["hand"]=sorted(map(card,h["hand"]),key=packed)
    return sha256(packed(x).encode()).hexdigest()
def ops(cid):
    return {op[0] for op in RULE.get(cid,{}).get("operations",())}
def special(h,a):
    if a["kind"]!="play_card":
        return False
    k=h["hand"][a["card"]]["id"]
    r=RULE.get(k,{})
    return (bool(ops(k)&{"Draw","AttackRandom","AddFixedCard"}) or r.get("CanGenerateUnknown")
            or r.get("coverage")=="specialized_execution_unexpanded")
def priority(h,a):
    k=h["hand"][a["card"]]["id"]
    r=RULE.get(k,{})
    return (any("choose" in x for x in r.get("knownCustomSemantics",())), "Draw" in ops(k),
            bool(r.get("CanGenerateUnknown")), -(a.get("cost") or 0), -a["index"])
def roots(h):
    unique={}
    for a in h["actions"]:
        if special(h,a):
            unique.setdefault(move(h,a),a)
    return sorted(unique.values(),key=lambda a:priority(h,a),reverse=True)
def size(c,field):
    rule=CARDS.get(c["id"],{})
    return rule.get(("Upgraded" if c["upgrade"] else "Base")+field) or 0
def tactic(h,style,merged):
    actions=h["actions"]
    if h["decision"]["phase"]!="combat":
        confirm=next((a for a in actions if a["kind"]=="confirm_selection"),None)
        choices=[a for a in actions if a["kind"]=="select_candidate"]
        if confirm and (h["decision"].get("selected") or not choices):
            return confirm
        def pick(a):
            c=h["decision"]["candidates"][a["choice"]]
            gain=size(c,"Block") if style!="attack" else size(c,"Damage")*max(1,size(c,"Hits"))
            if h["decision"].get("effect")!="MoveToDrawTop":
                gain=-gain
            return gain,move(h,a)
        return max(choices,key=pick) if choices else confirm
    end=next(a for a in actions if a["kind"]=="end_turn")
    if style=="end":
        return end
    plays=[a for a in actions if a["kind"]=="play_card"]
    if merged:
        # After forgetting within-draw order only use effects independent of hand order.
        plays=[a for a in plays if ops(h["hand"][a["card"]]["id"]) and
               ops(h["hand"][a["card"]]["id"]) <= {"Attack","AttackAll","GainBlock","ApplyPowerTarget","ApplyPowerSelf"}]
    def rank(a):
        c=h["hand"][a["card"]]
        p=a.get("preview") or {}
        block=size(c,"Block") if p.get("block") is None else p["block"]
        hit=size(c,"Damage") if p.get("damage_per_hit") is None else p["damage_per_hit"]
        damage=hit*(p.get("hits") or size(c,"Hits") or 1)
        draw="Draw" in ops(c["id"]) and not any(v["id"]=="NO_DRAW_POWER" for v in h.get("order_hooks",()))
        repeat=sum(card(z)==card(c) for z in h["hand"]) if block else 0
        # The repeat proposal spends remaining energy on inexpensive blocks even after the first copy is played.
        if style=="repeat":
            return (block>0,-(a.get("cost") or 0),repeat,block,damage,move(h,a))
        return (bool(draw and not a.get("cost")),block if style=="block" else damage,
                damage if style=="block" else block,-(a.get("cost") or 0),move(h,a))
    return max(plays,key=rank) if plays else end

# These listeners have an implemented AfterCardDrawn/Early effect in the frozen simulator.
DRAW_POWERS=set("HELLRAISER CONFUSED ITERATION PAGESTORM CHAINS_OF_BINDING CORROSIVE_WAVE SPEEDSTER CACOPHONY AUTOMATION".split())
def can_group(h,a):
    if a["kind"]!="play_card" or h["relics"]:
        return False
    k=h["hand"][a["card"]]["id"]
    if "Draw" not in ops(k) or ops(k)-{"Draw","ApplyPowerSelf","GainBlock","Attack"}:
        return False
    if any(p["id"].removesuffix("_POWER") in DRAW_POWERS for p in h.get("order_hooks",())):
        return False
    # A later hand-ordered exhaust/discard at turn end can distinguish otherwise equal draws.
    commuting={"BARRICADE","DEXTERITY","STRENGTH","POSSESS_STRENGTH","POSSESS_SPEED",
               "NO_DRAW","FRAIL","VULNERABLE","WEAK","RITUAL","ARTIFACT","PLATING"}
    if any(p["id"].removesuffix("_POWER") not in commuting for p in h.get("order_hooks",())):
        return False
    for c in h["deck"]+h["hand"]+h["discard"]+h["exhaust"]:
        mask=RULE.get(c["id"],{}).get("HookMask","unknown")
        if mask!="None" or c.get("enchantment") or c.get("affliction"):
            return False
    return True
def events(support,n):
    """Yield one replay transcript per multiset. Inline single-support draws consume no tokens."""
    keys=sorted(support)
    total=sum(support.values())
    if n==1:
        for k in sorted(keys,key=lambda k:-support[k]):
            yield (k,),support[k]/total
        return
    denominator=comb(total,n)
    def multisets(start,needed,prefix,ways):
        if needed==0:
            yield prefix,ways
            return
        capacity=sum(support[k] for k in keys[start:])
        for i in range(start,len(keys)):
            if capacity<needed:
                break
            k=keys[i]
            count=support[k]
            capacity-=count
            for take in range(min(needed,count),max(0,needed-capacity-1),-1):
                yield from multisets(i+1,needed-take,prefix+(k,)*take,ways*comb(count,take))
    for seq,ways in multisets(0,n,(),1):
        remain=Counter(support)
        tape=[]
        for k in seq:
            if len(remain)>1:
                tape.append(k)
            remain[k]-=1
            if not remain[k]:
                del remain[k]
        yield tuple(tape),ways/denominator
