"""Stable-boundary, replay, and source-mixture regression checks."""
import numpy as np
import pytest

from loop_learn import Pool, merge
from loop_policy import extract, legal_edge


def observation(cards):
    hand = [{"id": name} for name in cards]
    menu = [{"index": i, "kind": "play_card", "card": i}
            for i in range(len(cards))]
    return dict(hand=hand, actions=[*menu, dict(index=len(cards),kind="end_turn")])


def edge(source, target, **move):
    return {"from":source,"to":target,"action":move}


class PublicHistory:
    def update(self, history, public, action):
        return [*history, (len(public["hand"]), action["index"])]


def test_settlement_resolves_to_public_endturn_and_keeps_unscored():
    root, next_node = observation(["STRIKE","DEFEND"]), observation(["DEFEND"])
    graph = dict(type="sv4a_public_graph", observations={"0":root,"1":next_node},
        edges=[edge(0,1,kind="play_card",index=0,card="STRIKE"),
               edge(1,2,kind="end_turn",index=1),
               edge(2,3,kind="settle_turn"),
               edge(0,4,kind="play_card",index=1,card="DEFEND")],
        boundaries=[dict(id=2,kind="end_play_a"),dict(id=3,kind="random"),dict(id=4,kind="budget")])
    _, histories, ends, skipped = extract(graph, lambda x:x, PublicHistory(), root, [])
    assert histories == {0:[],1:[(2,0)]}
    assert [([step.index for step in path], item["kind"]) for item,path in ends] == [
        ([0,1],"end_play_a"),([0,1],"random")]
    assert skipped == {"budget":1}


def test_move_requires_current_public_card_instance():
    with pytest.raises(ValueError, match="same card"):
        legal_edge(observation(["DEFEND","STRIKE"]),dict(kind="play_card",index=0,card="STRIKE"))
    with pytest.raises(ValueError, match="legal menu"):
        legal_edge(observation([]),dict(kind="play_card",index=0,card="STRIKE"))


def test_source_pool_samples_trajectories_and_retains_action_padding():
    short = {"trajectory":np.array([0,1,1]),"actions":np.ones((3,1,2),dtype=np.float32),
             "cls":np.array([0,1,2]),"policy":np.zeros(3,dtype=np.int16)}
    long = {"trajectory":np.array([10,11]),"actions":np.ones((2,3,2),dtype=np.float32),
            "cls":np.array([6,7]),"policy":np.ones(2,dtype=np.int16)}
    rng=np.random.default_rng(3)
    first=Pool([short]).take(2,rng)
    second=Pool([long]).take(3,rng)
    batch=merge([first,second],"cpu")
    assert batch["policy"].tolist() == [0,0,1,1,1]
    assert 0 in first["cls"]
    assert batch["actions"].shape == (5,3,2)
    assert not batch["actions"][:2,1:].any()
