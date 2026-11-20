"""Weighting, legality and recurrent masking regressions for the optimized path."""
from copy import deepcopy

import pytest
import torch

from batched import forward
from features import BASE, FastDecision, protocol
from journal import fresh, state
from nosl_experience import public_observation
from nosl_model import WIDTH
import optimizer
from verify import compare_update


def observation(energy=3):
    card = dict(index=0, id="TWIN_STRIKE", upgrade=0, cost=1, enchantment=None, enchantment_amount=None,
                affliction=None, affliction_amount=None)
    attack = dict(kind="play_card", card=0, target=14, choice=None, potion=None, cost=1, preview={"hits": 2})
    end = dict(kind="end_turn", card=None, target=None, choice=None, potion=None, cost=None, preview=None)
    return dict(turn=1, hp=50, max_hp=80, block=0, energy=energy, draw_count=3,
                deck=[card, card], hand=[card] if energy else [], discard=[], exhaust=[],
                powers=[], potions=[], relics=[], enemies=[dict(index=14, hp=18, block=0, attack_hits=[7],
                                                               intents=["Attack"], powers=[])],
                actions=[dict(a, index=i) for i, a in enumerate((attack, end) if energy else (end,))])


@pytest.fixture(scope="module")
def batch():
    torch.set_num_threads(1)
    cfg = protocol.read(BASE / "formal.json")
    model, adam = fresh(cfg)
    saved = state(model, adam, cfg, 0)
    rows = []
    for i, n in enumerate((1, 5, 3, 2, 7)):
        row = dict(mode="sample", split="train", behavior=dict(model_sha256=saved["model_sha256"]),
                   model_version=protocol.MODEL_VERSION, transitions=[])
        h = torch.zeros(WIDTH)
        with torch.no_grad():
            for t in range(n):
                obs = public_observation(observation(int(t % 3 != 1)))
                decision = FastDecision(obs)
                logits, value, enriched, actions = model(decision, h)
                a = (t + i) % len(logits)
                row["transitions"].append(dict(observation=obs, action=obs["actions"][a], advanced=True,
                                               behavior_logp=logits.log_softmax(0)[a].item()))
                h = model.remember(h, enriched, actions[a])
        terminal = "predicted_win" if i % 2 else "death"
        row["feedback"] = dict(status=terminal, eligible=True, observation=dict(hp=20, max_hp=80, potions=[]))
        rows.append(row)
    # This deliberately incompatible row must be censored before constructing any graph.
    rows.append(dict(rows[0], feedback=dict(status="unsupported", eligible=False), transitions=[]))
    return saved, rows, cfg


def test_uneven_trajectories_preserve_actor_sum_critic_mean_and_updates(batch):
    result = compare_update(*batch, 0)
    assert result["reference"]["qualified"] == 5
    assert result["reference"]["steps"] == 18
    assert result["variants"]["batched"]["metrics"]["actor_gradient"] > 0


def test_public_masked_slots_and_distinct_recurrent_histories(batch):
    _, _, cfg = batch
    model, _ = fresh(cfg)
    original = observation()
    private_a = dict(original, draw_order=[1, 2], rng=[30], exact_root="a")
    private_b = dict(original, draw_order=[2, 1], rng=[40], exact_root="b")
    private_b = deepcopy(private_b)
    private_b["hand"][0]["native_instance_token"] = "other"
    a, b = [FastDecision(public_observation(x)) for x in (private_a, private_b)]
    c = FastDecision(public_observation(observation(0)))
    h = torch.zeros((3, WIDTH))
    with torch.no_grad():
        logits, values, _, _, valid = forward(model, [a, b, c], h)
        assert torch.equal(logits[0], logits[1]) and torch.equal(values[0], values[1])
        assert valid.tolist() == [[True, True], [True, True], [True, False]]
        assert logits[2].softmax(0).tolist() == [1., 0.]
        h[1].fill_(.5)
        _, values, states, _, _ = forward(model, [a, b, c], h)
        assert not torch.equal(states[0], states[1])
        assert not torch.equal(values[0], values[1])


def test_optimized_rejects_other_policy_and_nonadvanced_transition(batch):
    from journal import load

    saved, rows, cfg = batch
    model, adam = load(saved, cfg, 0)
    candidate = deepcopy(rows)
    candidate[-1]["behavior"]["model_sha256"] = "stale"
    with pytest.raises(ValueError, match="lineage"):
        optimizer.train(model, adam, candidate, cfg, saved["model_sha256"])
    candidate = deepcopy(rows)
    candidate[0]["transitions"][0]["advanced"] = False
    with pytest.raises(ValueError, match="Invalid chosen action"):
        optimizer.train(model, adam, candidate, cfg, saved["model_sha256"])


def test_comparison_restores_independent_adam_moments(batch):
    from verify import load

    _, _, cfg = batch
    model, adam = fresh(cfg)
    model.actor[-1].weight.square().sum().backward()
    adam.step()
    saved = state(model, adam, cfg, 1)
    key = "model_sha256"
    hashes = []
    for _ in range(2):
        candidate, optimizer = load(saved, cfg, 1)
        candidate.actor[-1].weight.sum().backward()
        optimizer.step()
        hashes.append(state(candidate, optimizer, cfg, 2)[key])
    assert hashes[0] == hashes[1] != saved[key]
