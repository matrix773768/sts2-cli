"""Locked cohorts and public deployment rules for the N4C pilot."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "m1-n4b"))
import design
from design import cohort, digest, read, LOGS, write

ARMS = ("g2", "search", "q_all", "q_gate", "plan_once", "plan_turn", "plan_all", "plan_gate",
        "q_budget", "plan_budget")
NOVEL = ("FOSSIL_STALKER_NORMAL", "PUNCH_CONSTRUCT_NORMAL", "SNAPPING_JAXFRUIT_NORMAL", "TUNNELER_WEAK")
NEW_HANDS = (
    ("IRON_WAVE", "BASH", "DEFEND_IRONCLAD", "HEAVY_BLADE", "INFLAME"),
    ("TWIN_STRIKE", "POMMEL_STRIKE", "BLOOD_WALL", "BASH", "DEFEND_IRONCLAD"),
    ("FLAME_BARRIER", "IRON_WAVE", "UPPERCUT", "STRIKE_IRONCLAD", "SHRUG_IT_OFF"),
    ("DEMON_FORM", "BLUDGEON", "IRON_WAVE", "DEFEND_IRONCLAD", "TWIN_STRIKE"),
)
LIMITS = dict(win_drop=.05, joint_loss_increase=2., severe_increase=.05)
PROTOCOL = dict(arms=ARMS, transitions=24, depth=8, action_cap=128, limits=LIMITS,
    natural_confirm=64, target_confirm=24, transfer_confirm=24, conditional_repeats=2,
    anchor="n4c-anchor", reference="n4c-reference", confidence=.95,
    primary="plan_gate vs g2 ordinary safety and familiar target efficacy; intersection",
    gate="combat, turn>=2, >=2 playable card slots, incoming>block, hp<=50, energy>=1",
    selective="one query per eligible turn (even after abstention); once = first combat query; all = query whenever free",
    budget_pair="first combat query on at most four turns, 24 transitions each, G2 direct elsewhere",
    safety="one-sided Bonferroni paired exact binary bounds per endpoint; family bootstrap common-win HP",
    mix="if development exposes deployment shift, fit target plus ordinary training-family endpoint advantages; fixed 1:1 domains, lambda=.1",
    unit="complete matched policy episodes, equal family weight; no terminal labels for incomplete branches")

def gate(h):
    playable = {a["card"] for a in h["actions"] if a["kind"]=="play_card"}
    return (h["decision"]["phase"]=="combat" and h["turn"]>=2 and h["hp"]<=50
            and h["energy"]>=1 and len(playable)>=2
            and sum(sum(e["attack_hits"]) for e in h["enemies"])>h["block"])

def decks(spec):
    return tuple(sorted(c["id"] for c in spec["deck"]))

def jobs(replication=False):
    prior = design.jobs()
    old = cohort.plan()
    ban = {j["family"] for j in prior if j["split"]!="confirm"} | {j[3] for j in old if j[2]!="confirm"}
    used = {decks(j[k]) for j in prior if j["split"]!="confirm" for k in ("spec","source_spec")}
    used.update(decks(j[1]) for j in old if j[2]!="confirm")
    raw = read(LOGS/"m1-dc1-formal/roots/development.json")["jobs"]
    reps = {j[3]:j[1] for j in raw if j[3] not in ban and j[1]["encounter"]!="KNOWLEDGE_DEMON_BOSS"}
    encounters = {j[1]["encounter"]:j[1] for j in raw+read(LOGS/"m1-dc1-formal/roots/train.json")["jobs"]}
    result=[]
    for family in sorted(reps,key=lambda f:digest(["n4c-family",f])):
        spec=reps[family]
        if decks(spec) in used:
            continue
        used.add(decks(spec))
        i=sum(j["domain"]=="natural" for j in result)
        split="dev" if i<8 else "confirm" if i<72 else "replication"
        idx=i if i<8 else i-8 if i<72 else i-72
        domains=["natural"]
        if split=="replication":
            domains+=["target"]
        elif idx<(4 if split=="dev" else 24):
            domains+=["target","transfer"]
        for domain in domains:
            native=spec|dict(hp=(55,80,100,70)[idx%4],max_hp=(80,80,100,80)[idx%4])
            counter=None
            if domain!="natural":
                names=design.HANDS if domain=="target" else NEW_HANDS
                hand=names[idx%4]
                enc=(design.ENCOUNTERS[(idx+idx//4)%2] if domain=="target" else NOVEL[(idx+idx//4)%4])
                front=["DEFEND_IRONCLAD","STRIKE_IRONCLAD","DEFEND_IRONCLAD","BASH","STRIKE_IRONCLAD"]
                import random
                rng=random.Random(digest(["n4c-hand",domain,family]))
                cards=[dict(id=c,upgrade=int(rng.random()<.25)) for c in hand]
                rng.shuffle(cards)
                counter=(0,9,None)[idx%3]
                native=spec|dict(act=encounters[enc]["act"],act_variant=encounters[enc]["act_variant"],
                    schema=2,ascension=0,encounter=enc,deck=[dict(id=c,upgrade=0) for c in front]+cards+spec["deck"],
                    hp=(14,24,36,50,20)[idx%5],max_hp=80,relics=[] if counter is None else ["NUNCHAKU"],potions=[])
                if decks(native) in used:
                    raise ValueError("derived deck collision")
                used.add(decks(native))
            result.append(dict(id=i,split=split,domain=domain,family=family,spec=native,counter=counter,
                enemy_hp=(24,38,47,61,32,42,55)[idx%7]))
        if i==(87 if replication else 71):
            break
    if len({j["family"] for j in result})!=(88 if replication else 72):
        raise ValueError("insufficient independent families")
    return result
