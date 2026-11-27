"""Public-card turn proposals. A play is bound by card type, upgrade and target at execution."""
from itertools import permutations

END=("end_turn",)
CONFIRM=("confirm_selection",)
def choices(h):
    out={}
    for a in h["actions"]:
        k=a["kind"]
        if k=="play_card":
            c=h["hand"][a["card"]];key=(c["id"],c["upgrade"],a.get("target"))
        elif k=="end_turn":key=END
        elif k=="confirm_selection":key=CONFIRM
        elif k=="select_candidate":
            c=h["decision"]["candidates"][a["choice"]];key=("pick",c["id"],c["upgrade"])
        else:continue
        out.setdefault(key,a["index"])
    return out

def select(h,remaining):
    legal=choices(h)
    if h["decision"]["phase"]!="combat":
        if CONFIRM in legal and h["decision"].get("selected"):return CONFIRM,remaining
        if h["decision"].get("effect")=="MoveToDrawTop":
            priority=["IMPERVIOUS","IRON_WAVE","HEADBUTT"]
        else:priority=["STRIKE_IRONCLAD","DEFEND_IRONCLAD"]
        picks=[k for k in legal if k[0]=="pick"]
        if picks:
            order=lambda k:(priority.index(k[1]) if k[1] in priority else len(priority),-k[2],k[1])
            return min(picks,key=order),remaining
        return CONFIRM,remaining
    return (remaining[0],remaining[1:]) if remaining else (END,())

SHRUG=("SHRUG_IT_OFF",0,None)
TRANCE=("BATTLE_TRANCE",0,None)
HEAD=("HEADBUTT",1,0)
IMP=("IMPERVIOUS",1,None)
DEF=("DEFEND_IRONCLAD",0,None)
BASH=("BASH",1,0)
BARRIER=("FLAME_BARRIER",0,None)
WAVE=("IRON_WAVE",1,0)

def proposals(tag,h):
    hand=h["hand"];opts={()}
    if tag=="rescue":
        # Every zero-, one- or two-play ordering using cards in the revealed hand.
        # No forced card from a later unseen draw. The END action is appended below.
        for n in (1,2):
            for seq in permutations(hand,n):
                if sum(c["cost"] for c in seq)>h["energy"]:continue
                variants=[next((key for key in choices(h) if key[:2]==(c["id"],c["upgrade"])),None) for c in seq]
                if all(variants):opts.add(tuple(variants))
    else:
        # A finite menu of resource tradeoffs: concentrate attacks on either enemy,
        # vary block/attack order, and allow Headbutt's public discard selection.
        priorities=[
          ("BASH","IRON_WAVE","STRIKE_IRONCLAD"),("HEADBUTT","POMMEL_STRIKE","IRON_WAVE","STRIKE_IRONCLAD"),
          ("IRON_WAVE","STRIKE_IRONCLAD","HEADBUTT","POMMEL_STRIKE"),("FLAME_BARRIER","IRON_WAVE","STRIKE_IRONCLAD"),
          ("BLOOD_WALL","HEADBUTT","IRON_WAVE","POMMEL_STRIKE","STRIKE_IRONCLAD"),
          ("EXPECT_A_FIGHT","POMMEL_STRIKE","IRON_WAVE","HEADBUTT","STRIKE_IRONCLAD"),
          ("POMMEL_STRIKE","HEADBUTT","IRON_WAVE","STRIKE_IRONCLAD"),("IRON_WAVE","FLAME_BARRIER","HEADBUTT","STRIKE_IRONCLAD")]
        legal=choices(h)
        for target in (0,1):
            for priority in priorities:
                seq=[];energy=h["energy"]
                for cid in priority:
                    for c in sorted((v for v in hand if v["id"]==cid),key=lambda v:-v["upgrade"]):
                        move=next((k for k in legal if k[:2]==(cid,c["upgrade"]) and k[-1] in (None,target)),None)
                        if move and c["cost"]<=energy:
                            seq.append(move);energy-=c["cost"]
                opts.add(tuple(seq))
    return sorted(opts,key=repr)

def hand_key(h):
    return "|".join(f'{c["id"]}#{c["upgrade"]}' for c in h["hand"])
