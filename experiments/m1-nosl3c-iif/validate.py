"""Exercise each exclusion against a real positive native equality proof."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from audit import compare_menu, frozen_menu
from equivalence import qualifies, stamp


def test_menu():
    native = dict(decision="combat_play",player={"hp":10,"block":0},energy=0,stars=0,
                  hand=[dict(index=0,id="CARD.STRIKE_IRONCLAD",target_type="AnyEnemy",
                             can_play=False,legal_target_indices=[0])])
    obs = dict(decision={"phase":"combat"},hand=[{"id":"STRIKE_IRONCLAD"}], hp=10,block=0,
               energy=0,stars=0,actions=[{"kind":"end_turn"}])
    indices = {"enemy":[0]}
    try:
        frozen_menu(obs,native,indices)
    except ValueError:
        pass
    else:
        raise AssertionError("Old menu did not reproduce the affordability error")
    compare_menu(obs,native,indices)
    native["hand"][0]["can_play"] = True
    try:
        compare_menu(obs,native,indices)
    except ValueError:
        pass
    else:
        raise AssertionError("Legal action missing from menu was accepted")


def test_terminal(record):
    proof = record["equivalence_proof"]
    p,n,prior = (proof[k] for k in ("predicted","native","previous"))
    feedback = dict(status="death",eligible=True,actions=record["prediction"]["actions"],
                    observation=record["prediction"]["terminal_observation"])
    assert qualifies(record,feedback,prior,p,n,True)
    variants = []
    for field in ("hp","block","energy","P","D","R","E0","gold"):
        import re
        changed, matches = re.subn(rf"(?<=;){field}=[^;]*",f"{field}=IIF_DIFFERENCE",p,count=1)
        assert matches == 1, field
        copy = deepcopy(record)
        copy["prediction"]["audit_stamp"] = stamp(changed)
        assert not qualifies(copy,feedback,prior,changed,n,True), field
        variants.append(field)
    for name,patch in (
        ("still_playable",lambda r:r["native_after"].update(decision="combat_play")),
        ("different_result",lambda r:r["native_after"].update(victory=True)),
        ("native_gold",lambda r:r["native_after"]["player"].update(gold=-1)),
        ("different_stage",lambda r:r["native_before"].update(round=-1)),
        ("unverified_prefix",lambda r:r["previous"].update(stamp="unverified")),
    ):
        copy = deepcopy(record)
        patch(copy)
        assert not qualifies(copy,feedback,prior,p,n,True), name
        variants.append(name)
    assert not qualifies(record,feedback,prior,p,n,False)
    return variants + ["resumable", "unaffordable_native_menu", "missing_legal_action"]


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagnostics",type=Path)
    a=parser.parse_args()
    test_menu()
    source = json.loads(a.diagnostics.read_bytes())
    found = next(s["result"] for s in source if s["result"].get("equivalence_proof"))
    print(json.dumps(dict(rejections=test_terminal(found)),indent=2))
