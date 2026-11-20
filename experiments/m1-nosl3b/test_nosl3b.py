from collections import Counter
from contextlib import ExitStack, closing
import json
import random
import sqlite3

import pytest
import torch

from nosl3b_protocol import HERE, PARTITIONS, roots, validate
from nosl3b_episode import baseline, choose
from nosl3b_store import Store, restore, snapshot
from nosl_experience import public_observation
from nosl_model import Decision, Policy, WIDTH, checkpoint
from analyze import card_for, pressure_context


@pytest.fixture(scope="module")
def config():
    torch.set_num_threads(1)
    doc = json.loads((HERE / "formal.json").read_bytes())
    validate(doc)
    return doc


def test_recipe_groups_and_pressure_balance(config):
    all_roots = {split: list(roots(config, split)) for split in PARTITIONS[1:]}
    all_roots["train"] = [r for update in range(config["schedule"]["updates"]) for r in roots(config, "train", update)]
    combined = [r for group in all_roots.values() for r in group]
    assert len({r["id"] for r in combined}) == len(combined)
    assert len({r["spec"]["seed"] for r in combined}) == len(combined)
    train_roots = all_roots["train"]
    assert len(set(Counter(r["pressure"] for r in train_roots).values())) == 1
    assert sum(r["stocked"] for r in train_roots) * 2 == len(train_roots)
    pilot = {r["id"] for split in PARTITIONS for r in roots(config, split, pilot=True)}
    assert pilot.isdisjoint({r["id"] for r in combined})


def test_modes_sample_and_greedy(config):
    menu = [{"kind": "play_card"}, {"kind": "use_potion"}, {"kind": "end_turn"}]
    logits = torch.tensor([1., 3., 1.])
    assert choose(logits, "greedy", random.Random(1), menu) == (1, 0.)
    assert choose(torch.tensor([3., 3., 1.]), "greedy", random.Random(2), menu) == (0, 0.)
    close = torch.tensor([0., 1e-8, 0.])
    assert int(close.log_softmax(0).argmax()) == 0
    assert choose(close, "greedy", random.Random(1), menu) == (1, 0.)
    for seed in range(20):
        index, logp = choose(logits, "sample", random.Random(seed), menu)
        expected = baseline.draw(logits.log_softmax(0), random.Random(seed))
        assert index == expected and logp == logits.log_softmax(0)[index].item()
        masked, masked_logp = choose(logits, "without_potion", random.Random(seed), menu)
        assert masked != 1 and masked_logp == pytest.approx(-.69314718)


def test_persisted_adam_update_and_deduplication(config, tmp_path):
    model = Policy()
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"])

    def update(p, opt):
        opt.zero_grad()
        p.actor[-1].weight.square().sum().backward()
        opt.step()

    update(model, optimizer)
    db = tmp_path / "journal.sqlite"
    manifest = {"protocol": "test"}
    row = dict(root="root-a", arm="id", initialization=9, mode="sample", replicate=0, iteration=0)
    with closing(Store(db, manifest)) as store:
        store.append("train", 0, row["root"], [row], 1.)
        store.save(0, snapshot({"test": model}, {"test": optimizer}), {"updates": 1})
        with pytest.raises(sqlite3.IntegrityError):
            store.append("train", 0, row["root"], [row], 1.)
    with closing(Store(db, manifest)) as store:
        assert store.done("train", 0) == {"root-a"}
        assert list(store.rows("train")) == [row]
        saved, stats = store.load(0)
        assert stats == {"updates": 1}
        models, optimizers = restore(saved, config, resume=True)
    update(model, optimizer)
    update(models["test"], optimizers["test"])
    assert checkpoint(model) == checkpoint(models["test"])
    with pytest.raises(ValueError, match="Cannot resume"):
        Store(db, {"protocol": "different"})


def test_real_guard_and_target_interventions(config):
    host = HERE.parents[1] / "logs/m1-nosl3a-build/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll"
    if not host.is_file():
        pytest.skip("Build the frozen NOSL3A worker before real-engine validation")
    logs = HERE.parents[1] / "logs/nosl3b-tests"
    logs.mkdir(exist_ok=True)
    env = baseline.Prediction(logs)
    root = next(r for r in roots(config, "train") if r["family"] == "strength-target")
    root["spec"] |= dict(seed="NOSL3ACHECK", hp=1, potions=[None],
                         deck=[dict(id=card, upgrade=0) for card in
                               ("INFLAME", "TWIN_STRIKE", "FLAME_BARRIER", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD")])

    def reset(g):
        return g.request("i1_n2_reset", arm="A", cap=96, potions=True, rejected=[])["episode"]

    def step(g, state, action):
        return g.request("i1_n2_step", index=action["index"], position=state["actions"])["episode"]

    with ExitStack() as stack:
        game, _, _ = env.open(stack, root)
        first = reset(game)
        obs = public_observation(first["observation"])
        assert pressure_context(obs)["lethal_incoming_proxy"]
        twin = [a for a in obs["actions"] if card_for(obs, a) == "TWIN_STRIKE"]
        assert len(twin) == 2 and twin[0]["target"] != twin[1]["target"]
        initial_hp = [e["hp"] for e in obs["enemies"]]
        for action in twin:
            state = step(game, reset(game), action)
            after_hp = [e["hp"] for e in state["observation"]["enemies"]]
            assert [idx for idx, (x, y) in enumerate(zip(initial_hp, after_hp, strict=True)) if y < x] == [action["target"]]
        end = obs["actions"][-1]
        assert end["kind"] == "end_turn"
        death = step(game, reset(game), end)
        assert death["status"] == "death"
        guard = next(a for a in obs["actions"] if card_for(obs, a) == "FLAME_BARRIER")
        blocked = step(game, reset(game), guard)
        guarded = public_observation(blocked["observation"])
        assert not pressure_context(guarded)["lethal_incoming_proxy"]
        survived = step(game, blocked, guarded["actions"][-1])
        assert survived["status"] == "active" and survived["observation"]["hp"] == 1
        game.request("i1_n2_close")
        native = game.execute_action({"action": "play_card", "args": {"card_index": guard["card"]}})
        assert native["player"]["block"] == guarded["block"]
        native = game.execute_action({"action": "end_turn"})
        assert native["decision"] == "combat_play" and native["player"]["hp"] == 1

    d = Decision(obs)
    d.rule_values.requires_grad_()
    history = torch.zeros(WIDTH)
    for mechanics, relations in ((True, True), (False, True), (True, False)):
        torch.manual_seed(70)
        p = Policy(mechanics, relations)
        logits = p(d, history)[0]
        derived = torch.autograd.grad(logits.square().sum(), [d.rule_values, p.relation[0].weight], allow_unused=True)
        assert bool(derived[0] is not None and derived[0].abs().max() > 0) == mechanics
        assert bool(derived[1] is not None and derived[1].abs().max() > 0) == relations
