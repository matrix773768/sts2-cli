from contextlib import closing
import runpy
from time import monotonic

import pytest
import torch

from journal import Journal, fresh
from audit_value import hp_calibration
from learning import train
from protocol import HERE, ROOT, digest, policy_seed, read, root
from worker import Environment, InvariantError, Worker, verify_resources
from nosl_model import checkpoint

semantic = runpy.run_path(str(HERE / 'benchmark.py'))['semantic']
qualify = runpy.run_path(str(HERE / 'run.py'))['qualify']


@pytest.fixture(scope="module")
def config():
    torch.set_num_threads(1)
    return read(HERE / "pilot.json")


def test_independent_no_resource_roots_and_sampling(config):
    items = [root(config, group, i) for group in ("train", "selection", "report")
             for i in range(len(config[group]))]
    assert len({r["id"] for r in items}) == len(items)
    assert len({r["spec"]["seed"] for r in items}) == len(items)
    assert all(not r["spec"]["potions"] and not r["spec"]["relics"] for r in items)
    train_root = items[0]
    a, b = (policy_seed(config, train_root, "sample", i, 0) for i in range(2))
    assert a != b and a == policy_seed(config, train_root, "sample", 0, 0)
    with pytest.raises(InvariantError):
        verify_resources(dict(relics=[], potions=["FLEX_POTION"], actions=[]))
    with pytest.raises(InvariantError):
        verify_resources(dict(relics=["BURNING_BLOOD"], potions=[], actions=[]))


def test_checksum_stop_without_discarding_checkpoint(config, tmp_path):
    ident = {"protocol": "check"}
    path = tmp_path / "trial.sqlite"
    with closing(Journal(path, ident)) as j:
        j.save(0, {"marker": torch.tensor(1)}, {})
        j.commit_root("train", 0, dict(root="a", rows=[], timing={"total_ms": 1}))
        assert j.done("train", 0) == {"a"}
        with j.db:
            j.db.execute("UPDATE roots SET rows=? WHERE root='a'", (b"corruption",))
        with pytest.raises(ValueError, match="checksum"):
            list(j.batches("train", 0))
        assert j.load(0)[0]["marker"] == 1
    with pytest.raises(ValueError, match="checksum"):
        Journal(path, ident)


def test_qualification_explicitly_counts_censors(config):
    def label(status):
        return {"feedback": dict(status=status, eligible=status in ("death", "predicted_win"))}

    qualify([label("death"), label("predicted_win"), label("death"), label("truncated")], config, "test")
    with pytest.raises(RuntimeError, match="2/4 qualified"):
        qualify([label("death"), label("predicted_win"), label("unsupported"), label("truncated")], config, "test")
    with pytest.raises(RuntimeError, match="1/4 faults"):
        qualify([label("death"), label("predicted_win"), label("death"), label("timeout")], config, "test")


@pytest.fixture(scope="module")
def env():
    if not (ROOT / "logs/m1-nosl3c-build/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll").exists():
        pytest.skip("Build NOSL3C research host for native tests")
    output = ROOT / "logs/nosl3c-tests"
    (output / "audit-only").mkdir(parents=True, exist_ok=True)
    return Environment(output)


def test_real_cold_resident_aba_and_head_inactive(config, env):
    items = [root(config, "bench", i) for i in (0, 1, 0)]
    model, optimizer = fresh(config)
    model_hash = digest(checkpoint(model))
    modes = [("sample", 0), ("sample", 1)]
    reference = {}
    for resident in (False, True):
        with closing(Worker(env, config, resident, cache=resident)) as worker:
            warm = 0
            for item in items:
                batch, audit = worker.attempt(item, 0, model_hash, model, modes)
                stamp = semantic(batch, audit)
                assert stamp == reference.setdefault(item["id"], stamp)
                warm += batch["timing"]["resident"]
            if resident:
                assert warm >= 1
                assert worker.game is not None
                worker.game.deadline = monotonic() - 1
                batch, audit = worker.attempt(items[0], 0, model_hash, model, modes)
                assert batch["timing"]["lease_recycled"] and not batch["timing"]["resident"]
                assert semantic(batch, audit) == reference[items[0]["id"]]
    training = root(config, "train", 0)
    with closing(Worker(env, config, False)) as worker:
        batch, _ = worker.attempt(training, 0, model_hash, model, modes)
    orig = model.critic[-1].weight[2].detach().clone()
    stats = train(model, optimizer, batch["rows"], config, model_hash)
    assert torch.equal(orig, model.critic[-1].weight[2])
    assert stats["actor_gradient"] > 0 and stats["critic_gradient_after_clip"] > 0
    assert stats["model_sha256"] != model_hash

def test_hp_calibration_is_win_weighted_and_root_weighted():
    def row(root_id, won, prediction):
        return dict(root=root_id, transitions=[{"value": [0.5, prediction, 0.]}],
                    feedback=dict(status="predicted_win" if won else "death", eligible=True,
                                  observation=dict(hp=50, max_hp=100, potions=[])))
    data = hp_calibration([row("a", True, .3), row("a", False, .3), row("b", False, .1)])
    assert data["roots"] == 2
    assert data["predicted_mean"] == pytest.approx(.2)
    assert data["observed_mean"] == pytest.approx(.125)
    assert data["calibration_error"] == pytest.approx(.075)
