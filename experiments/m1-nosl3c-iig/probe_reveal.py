"""Native regression for a bounded engine-owned draw reveal and selected instance."""
import argparse
from contextlib import ExitStack
from copy import deepcopy
import os

import torch
from hashlib import sha256
from pathlib import Path
from types import FunctionType

from bridge import bind, targets
from nosl_experience import save_json
from qualify_native import compare_menu, native_action, qualify

SPEC = dict(schema=1,act=1,character="Ironclad",ascension=0,seed="IIGREVEAL",hp=80,max_hp=80,
            relics=[],potions=[],encounter="SHRINKER_BEETLE_WEAK",
            deck=[dict(id=card,upgrade=upgrade) for card,upgrade in
                  [("SEEKER_STRIKE",0)]*5+[("STRIKE_IRONCLAD",0),("STRIKE_IRONCLAD",1),
                   ("DEFEND_IRONCLAD",0),("DEFEND_IRONCLAD",1),("BASH",0),("IRON_WAVE",0),
                   ("POMMEL_STRIKE",0),("TWIN_STRIKE",0)]])
SOURCE = "SEEKER_STRIKE"


def probe(output,solver):
    targets.configure()
    versions=bind(output,solver)
    with ExitStack() as stack:
        pred,native=[targets.open_worker(output,stack,versions) for _ in range(2)]
        left,_=targets.CAPTURE(pred,SPEC)
        right,_=targets.CAPTURE(native,SPEC)
        assert left["native"] == right["native"]
        native.teacher_frames,native.teacher_choices=[],[]
        native.request("i1_begin")
        before=pred.request("i1_n2_reset",arm="A",cap=128,potions=False,rejected=[])["episode"]
        obs=targets.project(before["observation"])
        draw=left["native"]["draw"]
        by_key={f"{c['id']}+{c['upgrade']}": i for i,c in enumerate(SPEC["deck"])}
        hidden_keys=[key.split("|",1)[0] for key in draw if not key.startswith(SOURCE)]
        i,j=next((by_key[a],by_key[b]) for a in hidden_keys for b in hidden_keys if a!=b)
        assert obs["decision"]["phase"]=="combat" and "candidates" not in obs["decision"]
        act=next(a for a in obs["actions"] if a["card"] is not None and obs["hand"][a["card"]]["id"]==SOURCE)
        game=native_action(native,"play_card",card_index=act["card"],target_index=act["target"])
        first=pred.request("i1_n2_step",position=0,index=act["index"])["episode"]
        assert first["status"]=="active",first
        choice=targets.project(first["observation"])
        compare_menu(choice,game)
        cards=choice["decision"]["candidates"]
        assert choice["decision"]["pile"]=="Draw" and 1<len(cards)<obs["draw_count"]
        assert first["interaction_trace"]["captured"]
        candidate=choice["actions"][-1]
        assert candidate["kind"]=="select_candidate"
        waiting=pred.request("i1_n2_step",position=1,index=candidate["index"])["episode"]
        selected=targets.project(waiting["observation"])
        commit=next(a for a in selected["actions"] if a["kind"]=="confirm_selection")
        native_action(native,"select_cards",indices=str(candidate["choice"]))
        ended=pred.request("i1_n2_step",position=2,index=commit["index"])["episode"]
        frame=native.request("i1_iib_native_stamp")
        stamp=sha256(frame["state"][0]["exact_continuation_state"].encode()).hexdigest()
        assert stamp==ended["audit_stamp"] and ended["status"]=="active"
        pred.request("i1_n2_close")
        action=ended["audit_action"]
    twin=deepcopy(SPEC)
    twin["deck"][i],twin["deck"][j]=twin["deck"][j],twin["deck"][i]
    with ExitStack() as stack:
        alternate=targets.open_worker(output,stack,versions)
        source,_=targets.CAPTURE(alternate,twin)
        assert source["native"]["draw"] != draw
        state=alternate.request("i1_n2_reset",arm="A",cap=128,potions=False,rejected=[])["episode"]
        alternate_obs=targets.project(state["observation"])
        assert obs==alternate_obs
        from training import Policy
        policy=Policy().eval()
        memory=torch.zeros(policy.history.hidden_size)
        with torch.no_grad():
            a,b=[policy(targets.Decision(view),memory)[0].softmax(0) for view in (obs,alternate_obs)]
        assert torch.equal(a,b)
        nxt=alternate.request("i1_n2_step",position=0,index=act["index"])["episode"]
        assert (nxt.get("interaction_trace") or {}).get("captured")
        alternate.request("i1_n2_close")
        assert alternate.request("f1_audit")["stamp"] == source["identity"]["live"]
    result=dict(versions=versions,spec=SPEC,candidates=cards,candidate=candidate["choice"],
                after_sha256=stamp,matched=True,private_plan=action,
                hidden_draw_pair_equal=True,pending_close_source_equal=True)
    save_json(output/"reveal.json",result)
    # A separate full route uses one copy of every public card state.
    full_spec=SPEC | {"deck": [SPEC["deck"][0], *SPEC["deck"][5:]]}
    for seed in ("IIGREVEAL","IIGFULL1","IIGFULL2","IIGFULL3","IIGFULL4","IIGFULL5"):
        full_spec["seed"]=seed
        with ExitStack() as stack:
            game=targets.open_worker(output,stack,versions)
            root,_=targets.CAPTURE(game,full_spec)
            if any(c["id"]=="CARD."+SOURCE for c in root["public_root"]["hand"]):
                break
    full=qualify(output,versions,full_spec,"STRIKE_IRONCLAD",opening=(SOURCE,))
    save_json(output/"full.json",full | {"spec":full_spec})
    assert full["terminal"]=="predicted_win" and full["native_terminal"]
    blocked=qualify(output,versions,SPEC,SOURCE)
    assert blocked["terminal"]=="unsupported" and blocked["exact_boundaries"]==1
    save_json(output/"ambiguous.json",blocked)
    dll=targets.BANK.f1.i2.SOLVER
    os.environ["I1_SOLVER"]=str(dll)
    original=versions|dict(solver="0.51.5",solver_sha256=sha256(dll.read_bytes()).hexdigest())
    direct=[]
    # Preserve the native-selected instance; bind the original replay's
    # identity context in its historical filtered-pile presentation order.
    observed={f"{c['id']}+{c['upgrade']}" for c in cards}
    old_order=[key.split("|",1)[0] for key in draw if key.split("|",1)[0] in observed]
    resolved=deepcopy(action)
    context=resolved["choice"]["context_id"].split(":",2)
    resolved["choice"]["context_id"]=":".join([*context[:2],",".join(old_order)])
    for plan in (action|{"choice":None}, resolved):
        with ExitStack() as stack:
            game=targets.open_worker(output,stack,original)
            targets.CAPTURE(game,SPEC)
            reply=game.request("i1_iif_direct",fixed_actions=[plan])
            direct.append(reply["boundaries"][0])
    assert direct[0]["boundary"]=="PendingChoice" and direct[1]["boundary"]=="None"
    save_json(output/"direct.json",dict(engine=original,unanswered=direct[0],answered=direct[1]))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--solver",type=Path,required=True)
    a=parser.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    probe(a.output.resolve(),a.solver.resolve())
