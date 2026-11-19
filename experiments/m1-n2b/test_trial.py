from collections import Counter
from types import SimpleNamespace as Obj

from train import CONFIG, FEATURES, HERE, rank, sample, schedule, scores, stamp, update
from policy import decide, features
from analyze import read

COHORT = HERE.parent / "m1-n2a2"


def test_public_features_distinguish_unknown_and_zero_and_keep_end_turn():
    actor = Obj(id="STRIKE_IRONCLAD")
    enemy = Obj(hp=5, block=2, attack_hits=(3,4))
    observation = Obj(hand=(actor,), enemies=(enemy,), block=1)
    end = Obj(card=None)
    unknown = Obj(card=0, target=0, preview=None, cost=1, choice=None)
    lethal = Obj(card=0, target=0, preview=Obj(damage_per_hit=8,hits=1,block=None,draw=None),
                 cost=1, choice=None)
    assert len(features(observation, end, 7)) == 15
    assert features(observation, unknown, 7)[FEATURES.index("missing_damage")] == 1
    assert features(observation, lethal, 7)[FEATURES.index("lethal")] == 1
    assert decide(observation, [end, lethal], [0]*15) is end
    assert decide(observation, [end, lethal], CONFIG["initial_mean"]) is lethal


def test_optimizer_missing_is_not_death_and_variance_floor():
    def row(status, outcome=None):
        return dict(terminal=dict(status=status, feedback=dict(combat_terminal=outcome)))
    win = row("predicted_win", {"hp":8,"max_hp":16})
    incomplete = scores([win, row("truncated")])
    complete = scores([row("death"), row("death")])
    assert incomplete["missing"] == 1 and "death" not in incomplete["stops"]
    assert rank(complete) > rank(incomplete)
    assert scores([win])["hp_sum"] == .5
    mu = [0]*15
    assert sample([100]*15,mu,[1]*15) == [4.0]*15
    _, sd = update([mu]*4, mu, [0]*15)
    assert sd == [CONFIG["sd_floor"]]*15


def test_schedule_is_balanced_and_all_phases_are_budgeted():
    plan = read(COHORT/"manifest.json")
    batches = schedule(plan["cases"])
    assert len({i["case"]["id"] for b in batches for i in b}) == 48
    for batch in batches:
        assert sorted(Counter(i["case"]["spec"]["encounter"] for i in batch).values()) == [3]*4
    data = read(HERE/"ledger.json.gz")
    fixed = read(HERE/"models.json")
    digest = fixed.pop("sha256")
    assert digest == data["locked_model_sha256"] == stamp(fixed)
    assert data["manifest_sha256"] == stamp(plan)
    counts = Counter()
    for batch, expected in zip(data["passes"][:4], data["schedule"], strict=True):
        for model in batch["models"]:
            selected = [r for r in batch["rows"] if r["model"] == model["id"]]
            assert len(selected) == 12
            assert {r["id"] for r in selected} == set(expected)
            counts[model["method"]] += len(selected)
    assert counts == {"cem":576,"random":576}
    assert [len(r["rows"]) for r in data["passes"][-2:]] == [240,96]
    assert [m["id"] for m in fixed["models"]] == [m["id"] for m in data["passes"][-1]["models"]]
    cases = {i["case"]["id"]:i["case"]["cohort"] for i in plan["cases"]}
    for phase, split in ((data["passes"][-2], "selection"), (data["passes"][-1], "report")):
        assert {cases[r["id"]] for r in phase["rows"]} == {split}


def test_paired_initial_draws_yield_identical_outcomes():
    first = read(HERE/"ledger.json.gz")["passes"][0]
    rows = {(r["id"],r["model"]):r for r in first["rows"]}
    for model in first["models"][:12]:
        peer = model["id"].replace("cem-","random-")
        assert model["weights"] == next(m["weights"] for m in first["models"] if m["id"] == peer)
        for root in {r["id"] for r in first["rows"]}:
            a,b = (rows[root,index]["terminal"] for index in (model["id"],peer))
            assert {k:v for k,v in a.items() if not k.endswith("_ms")} == {
                k:v for k,v in b.items() if not k.endswith("_ms")}


def test_report_fixed_controls_reproduce_qualification_outcomes():
    prior = read(COHORT/"benchmark.json.gz")
    report = read(HERE/"ledger.json.gz")["passes"][-1]
    lookup = {(row["id"],row["defense_first"]):row for batch in prior["batches"]
              for row in batch["rows"] if row["cap"] == 96}
    for row in report["rows"]:
        if row["model"].startswith("fixed-"):
            control = lookup[row["id"],row["defense_first"]]
            assert row["terminal"]["feedback"] == control["terminal"]["feedback"]
            assert row["terminal"]["audit_stamps"] == control["terminal"]["audit_stamps"]


def test_snapshot_retries_a_transient_windows_lock(monkeypatch, tmp_path):
    import train
    calls = []

    def atomic(path, data):
        calls.append((path, data))
        if len(calls) == 1:
            raise PermissionError("temporary sharing violation")

    monkeypatch.setattr(train.base.bank, "atomic", atomic)
    monkeypatch.setattr(train, "sleep", lambda _: None)
    train.snapshot(tmp_path, {"complete": True})
    assert calls == [(tmp_path / "ledger.json", {"complete": True})] * 2
