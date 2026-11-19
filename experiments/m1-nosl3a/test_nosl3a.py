from contextlib import ExitStack
from copy import deepcopy
import gzip
from hashlib import sha256
import json
import random

import pytest
import torch

from nosl_experience import digest, public_observation, targets, terminal
from nosl_model import Decision, Policy, WIDTH, restore, static
from nosl_run import HERE, Prediction, record, roots, rollout, train


@pytest.fixture(scope="module")
def config():
    torch.set_num_threads(1)
    return json.loads((HERE / "config.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def prediction():
    if not (HERE.parents[1] / "logs/m1-nosl3a-build/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll").is_file():
        pytest.skip("Build the isolated NOSL worker before real-engine tests")
    result = HERE.parents[1] / "logs/nosl3a-tests"
    result.mkdir(exist_ok=True)
    return Prediction(result)


def begin(game, cap=96):
    state = game.request("i1_n2_reset", arm="A", cap=cap, potions=True, rejected=[])["episode"]
    assert state["status"] == "active", state["status"]
    return state


def apply(game, obs, position, predicate):
    choice = next(a for a in obs["actions"] if predicate(a))
    return game.request("i1_n2_step", position=position, index=choice["index"])["episode"]


def card_is(obs, action, card_id):
    return action.get("card") is not None and obs["hand"][action["card"]]["id"] == card_id


def fixture_root(config, cards, potion=False, encounter="SHRINKER_BEETLE_WEAK"):
    root = next(roots(config, "train", 0, True))
    root["spec"] |= dict(seed="NOSL3ACHECK", encounter=encounter,
                         potions=["FLEX_POTION" if potion else None],
                         deck=[dict(id=card, upgrade=0) for card in cards.split()])
    return root


def test_terminal_qualification_and_group_isolation(config):
    train_roots = [r for i in range(config["training_rounds"]) for r in roots(config, "train", i, False)]
    report = list(roots(config, "report", 0, False))
    assert {r["group"] for r in train_roots} == {"train"}
    assert not {r["family"] for r in train_roots} & {r["family"] for r in report}
    assert len({r["spec"]["seed"] for r in train_roots + report}) == len(train_roots + report)
    end = dict(hp=20, max_hp=80, potions=["FLEX_POTION", None, None])
    assert targets(terminal(dict(status="predicted_win", terminal_observation=end), None)) == (1, .25, 1 / 3)
    assert targets(terminal(dict(status="death"), None)) == (0, 0, 0)
    for state, status in [(dict(status="unsupported"), "unsupported"),
                          (dict(status="truncated", detail="wall_cap"), "timeout"),
                          (dict(status="truncated", detail="action_cap"), "truncated"),
                          (dict(status="error"), "error")]:
        result = terminal(state, None)
        assert result["status"] == status and targets(result) is None
    assert targets(terminal(dict(status="predicted_win"), {"kind": "end_turn"})) is None
    unknown_ids, unknown_values = static("UNREGISTERED", 0)
    assert unknown_ids[2] and unknown_ids[3]
    assert unknown_values[:4] == [0., 0., 0., 0.]
    assert unknown_values[12] == 1.  # Explicit unsupported effect node, with no numeric magnitude.


def test_hidden_draw_and_permutation(config, prediction):
    root = fixture_root(config, "INFLAME TWIN_STRIKE BASH SHRUG_IT_OFF STRIKE_IRONCLAD "
                        "DEFEND_IRONCLAD POMMEL_STRIKE IRON_WAVE TWIN_STRIKE FLAME_BARRIER",
                        encounter="CORPSE_SLUGS_WEAK")
    root["spec"]["act_variant"] = "UNDERDOCKS"
    with ExitStack() as stack:
        game, _, _ = prediction.open(stack, root)
        first = begin(game)
        game.request("i1_n2_close")
        cards = game.request("synthetic_snapshot")["draw"]
    other = deepcopy(root)
    order = [c.split("+", 1)[0] for c in cards]
    left, right = next((a, b) for a in order for b in order if a != b
                       and sum(c["id"] == a for c in root["spec"]["deck"]) == 1
                       and sum(c["id"] == b for c in root["spec"]["deck"]) == 1)
    deck = other["spec"]["deck"]
    i, j = (next(i for i, c in enumerate(deck) if c["id"] == key) for key in (left, right))
    deck[i], deck[j] = deck[j], deck[i]
    with ExitStack() as stack:
        game, _, _ = prediction.open(stack, other)
        assert game.request("synthetic_snapshot")["draw"] != cards
        second = begin(game)
        assert first["audit_stamp"] != second["audit_stamp"]
        original, hidden_twin = [public_observation(s["observation"]) for s in (first, second)]
        assert original == hidden_twin
        assert "audit_stamp" not in original and "draw" not in original

    torch.manual_seed(26)
    model = Policy()
    history = torch.zeros(WIDTH)
    with torch.no_grad():
        expected, values, _, _ = model(Decision(original), history)
        assert torch.equal(expected, model(Decision(hidden_twin), history)[0])
    altered = deepcopy(original)
    for zone in ("deck", "hand", "discard", "exhaust", "enemies"):
        altered[zone].reverse()
    hand = {c["index"]: 83 - c["index"] for c in altered["hand"]}
    enemy = {c["index"]: 56 - c["index"] for c in altered["enemies"]}
    assert len(enemy) >= 2
    for key, mapping in (("hand", hand), ("enemies", enemy)):
        for row in altered[key]:
            row["index"] = mapping[row["index"]]
    altered["actions"].reverse()
    for index, action in enumerate(altered["actions"]):
        action.update(index=index, target=enemy.get(action["target"]),
                      card=hand.get(action["card"]), choice=hand.get(action["choice"]))
    with torch.no_grad():
        reordered, reordered_values, *_ = model(Decision(altered), history)
    torch.testing.assert_close(expected, reordered.flip(0), rtol=1e-5, atol=1e-7)
    torch.testing.assert_close(values, reordered_values)
    legal = [a for a in original["actions"] if a["target"] is not None]
    assert len({a["target"] for a in legal}) >= 2


def test_real_local_rules_and_nonlinearity(config, prediction):
    root = fixture_root(config, "INFLAME TWIN_STRIKE BASH STRIKE_IRONCLAD DEFEND_IRONCLAD", potion=True)
    with ExitStack() as stack:
        game, _, _ = prediction.open(stack, root)
        before = begin(game)
        obs = public_observation(before["observation"])
        for position, index in ((1, 0), (0, -1)):
            assert game.request("i1_n2_step", position=position, index=index)["episode"]["status"] == "invalid_action"
        after = apply(game, obs, 0, lambda a: card_is(obs, a, "INFLAME"))
        boosted = public_observation(after["observation"])

        def twin(o):
            return next(a for a in o["actions"] if card_is(o, a, "TWIN_STRIKE"))["preview"]

        base, buff = twin(obs), twin(boosted)
        assert base["hits"] == buff["hits"] == 2
        assert (buff["damage_per_hit"] - base["damage_per_hit"]) * 2 == 4
        assert obs["energy"] >= 2
        game.request("i1_n2_close")
        begin(game)
        bash = apply(game, obs, 0, lambda a: card_is(obs, a, "BASH"))
        one = public_observation(bash["observation"])
        assert one["energy"] == 1
        exhausted = apply(game, one, 1, lambda a: card_is(one, a, "INFLAME"))
        assert not any(card_is(exhausted["observation"], a, "TWIN_STRIKE") for a in exhausted["observation"]["actions"])
        game.request("i1_n2_close")
        begin(game, cap=1)
        capped = apply(game, obs, 0, lambda a: a["kind"] == "use_potion")
        assert capped["status"] == "truncated" and not any(capped["terminal_observation"]["potions"])
        assert targets(terminal(capped, None)) is None
        game.request("i1_n2_close")
        # Reach an actual Twin Strike lethal with no Strength power.
        state = begin(game)
        for _ in range(20):
            o = public_observation(state["observation"])
            enemy = o["enemies"][0]
            available = [a for a in o["actions"] if card_is(o, a, "TWIN_STRIKE")]
            if available and available[0]["preview"]["damage_per_hit"] * 2 >= enemy["hp"] + enemy["block"]:
                won = apply(game, o, state["actions"], lambda a: card_is(o, a, "TWIN_STRIKE"))
                assert won["status"] == "predicted_win"
                break
            hit = next((a for a in o["actions"] if card_is(o, a, "BASH") or
                        card_is(o, a, "STRIKE_IRONCLAD")), o["actions"][-1])
            state = apply(game, o, state["actions"], lambda a: a["index"] == hit["index"])
        else:
            pytest.fail("Expected a Twin Strike lethal fixture")
        game.request("i1_n2_close")
        # Verify the potion/Strength transition via a native execution on the untouched source.
        native = game.execute_action({"action": "use_potion", "args": {"potion_index": 0}})
        assert any(p["amount"] == 5 and p["name"].startswith("STRENGTH_POWER") for p in native["player_powers"])

    torch.manual_seed(28)
    model = Policy()
    d = Decision(obs)
    with torch.no_grad():
        _, _, state, actions = model(d, torch.zeros(WIDTH))
        a = next(a["index"] for a in obs["actions"] if card_is(obs, a, "INFLAME"))
        b = next(a["index"] for a in obs["actions"] if card_is(obs, a, "TWIN_STRIKE"))
        card = model.card(torch.cat((model.ids(d.card_ids), model.ids(d.instance_ids).flatten(1),
                                     d.instance, model.rules(d.rule_ids).flatten(1), d.rule_values), dim=1))
        def relation(i, j, context):
            return model.relation(torch.cat((actions[i], card[d.refs[j, 0] - 1], context, torch.ones(4))))
        ab, ba = relation(a, b, state), relation(b, a, state)
        assert not torch.allclose(ab, ba)
        # Mixed finite difference rules out an additive card term plus a context term.
        difference = ab - ba - relation(a, b, -state) + relation(b, a, -state)
        assert difference.abs().max() > 1e-5


def test_real_survivor_and_on_policy_updates(config, prediction):
    root = fixture_root(config, "SURVIVOR SLICE SLICE STRIKE_SILENT STRIKE_SILENT")
    root["spec"] |= dict(character="Silent", max_hp=70, hp=70)
    torch.manual_seed(config["initialization_seed"])
    model = Policy()
    e = record(root, "mechanism", "test", prediction.versions, 12, 0)
    with ExitStack() as stack:
        game, _, _ = prediction.open(stack, root)
        initial = begin(game)
        o = initial["observation"]
        choices = [a for a in o["actions"] if a["kind"] == "play_with_discard"]
        assert len(choices) == 4 and len({a["choice"] for a in choices}) == 4
        for choice in choices:
            begin(game)
            step = game.request("i1_n2_step", index=choice["index"], position=0)["episode"]
            index = choice["choice"]
            used = o["hand"][index]
            assert step["actions"] == 1 and step["observation"]["discard"][0]["id"] == used["id"]
        game.request("i1_n2_close")
        audit = rollout(game, e, model, random.Random(12), config["action_cap"], prediction.rpc_error)
    assert e["feedback"]["status"] == "predicted_win", e["feedback"]
    # Cold native replay of this open test root compares every reached public state.
    with ExitStack() as stack:
        game, _, _ = prediction.open(stack, root)
        game.teacher_frames, game.teacher_choices = [], []
        game.request("i1_begin")
        for transition, private in zip(e["transitions"], audit[:-1], strict=True):
            action = dict(private["audit_action"])
            if isinstance(action["kind"], int):
                action["kind"] = ("PlayCard", "UsePotion", "EndTurn")[action["kind"]]
            chosen = transition["action"]
            if chosen["choice"] is not None and sum(
                a["card"] == chosen["card"] for a in transition["observation"]["actions"]
            ) == 1:
                action.pop("choice")
            reply = game.request("i1_step", action=action)
            assert reply["type"] == "i1_state", reply["type"]
            after = transition["next_observation"]
            if reply["terminal"]:
                assert reply["state"][0]["player_hp"] == after["hp"]
                assert after == e["feedback"]["observation"]
            else:
                native = reply["decision"]
                assert native["energy"] == after["energy"]
                assert native["player"]["hp"] == after["hp"]
                assert [c["id"] for c in native["hand"]] == ["CARD." + c["id"] for c in after["hand"]]
                assert [n["hp"] for n in native["enemies"]] == [n["hp"] for n in after["enemies"]]
        assert reply["terminal"]
    assert e["feedback"]["eligible"], e["feedback"]
    for index, transition in enumerate(e["transitions"]):
        assert transition["position"] == index and transition["advanced"]
        assert transition["action"] in transition["observation"]["actions"]
        if index + 1 < len(e["transitions"]):
            assert transition["next_observation"] == e["transitions"][index + 1]["observation"]
    opt = torch.optim.Adam(model.parameters(), lr=config["learning_rate"])
    report = train(model, opt, [e], config)
    assert report["policy_gradient"] > 0 and report["head_gradients"]["critic"] > 0
    assert report["behavior_logp_error"] < 2e-5 and report["restore_exact"]
    assert report["witness"]["before"] != report["witness"]["after"]
    assert report["witness"]["value_before"] != report["witness"]["value_after"]



def test_choice_gap_refuses_partial_menu(config, prediction):
    root = fixture_root(config, "HEADBUTT STRIKE_IRONCLAD STRIKE_IRONCLAD DEFEND_IRONCLAD DEFEND_IRONCLAD")
    with ExitStack() as stack:
        game, _, _ = prediction.open(stack, root)
        state = game.request("i1_n2_reset", arm="A", cap=96, potions=True, rejected=[])["episode"]
        assert state["status"] == "unsupported" and "HEADBUTT" in state["detail"]
        assert state.get("observation") is None and targets(terminal(state, None)) is None
        game.request("i1_n2_close")


def test_frozen_evidence(config):
    folder = HERE / "evidence"
    summary = json.loads((folder / "summary.json").read_bytes())
    payload = gzip.decompress((folder / "public.jsonl.gz").read_bytes())
    assert sha256(payload).hexdigest() == summary["public_ledger"]["sha256"]
    rows = [json.loads(line) for line in payload.splitlines()]
    assert len(rows) == summary["public_ledger"]["rows"] == 180
    grouped = {split: {e["root"] for e in rows if e["split"] == split} for split in ("train", "report")}
    assert len(grouped["train"]) == 32 and len(grouped["report"]) == 12
    assert grouped["train"].isdisjoint(grouped["report"])
    hashes = [summary["initial"]["mechanism"], summary["trained"]["mechanism"]]
    index = {e["root"]: e for e in rows if e["arm"] == "mechanism_initial"}
    assert all(len(e["transitions"]) == e["feedback"]["actions"] for e in index.values())
    e = next(iter(index.values()))
    step = e["transitions"][0]
    policies = []
    for phase, expected in zip(("initial", "trained"), hashes, strict=True):
        archived = json.loads(gzip.decompress((folder / f"mechanism-{phase}.json.gz").read_bytes()))
        assert digest(archived) == expected
        policies.append(restore(archived))
    with torch.no_grad():
        d = Decision(step["observation"])
        initial, trained = (p(d, torch.zeros(WIDTH))[0].log_softmax(0) for p in policies)
        assert initial[step["action"]["index"]].item() == step["behavior_logp"]
        assert not torch.equal(initial, trained)
