"""Cold, version-attested root construction and tiered frozen search execution."""
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from time import monotonic, perf_counter

from space import HERE, digest, inventory
import search as ls1
from loop import experience as ls1_experience, model
from ls1_design import STRATEGIES, file_hash
from semantics import CardInstance, DeckSpec

HOST = "m1-ls2a-build"
bank = ls1.bank
TRANSIENT = (TimeoutError, OSError, bank.f1.i2.engine_client.EngineCancelled)
RPC_ERROR = bank.f1.i2.StopRun
DIFFERENCE = ls1.f3a.Difference
ENCODER = digest([model.ENCODER, file_hash(HERE / "engine.py", True)])


def bind(output):
    names = ("build.py", "Catalog.cs", "Trajectory.cs", "engine.py", "space.py", "pipeline.py", "store.py")
    sources = {name: file_hash(HERE / name, True) for name in names}
    sources["ls1/search.py"] = file_hash(HERE.parent / "m1-ls1/search.py", True)
    sources["ls1/loop.py"] = file_hash(HERE.parent / "m1-ls1/loop.py", True)
    return ls1.setup(output, host=HOST) | {
        "producer": digest(sources),
        "ls2_encoder": ENCODER,
    }


def attest(game, versions):
    loaded = game.request("i1_s3a_identity")
    if (loaded["sha256"], loaded["version"].split("+", 1)[0]) != (
            versions["solver_sha256"], versions["solver"]):
        raise ValueError("Runtime Solver attestation failed")


def catalog(out, versions):
    with ls1.b1b.Session(out, monotonic() + 30, Event()) as game:
        attest(game, versions)
        return game.request("synthetic_catalog")


def public_projection(obs, resources, character, static):
    if obs["decision"] != "combat_play":
        raise ValueError("Expected public combat-play decision")
    p = obs["player"]
    gaps = set()
    cards = []
    for card in p["deck"]:
        modifiers = []
        for kind in ("enchantment", "affliction"):
            if kind not in card:
                continue
            if type(card.get(kind + "_amount")) is int:
                modifiers.append((kind, card[kind], card[kind + "_amount"]))
            else:
                gaps.add("public_modifier_amount_missing")
        cards.append(CardInstance(card["id"].removeprefix("CARD."), int(card["upgraded"]),
                                  tuple(modifiers)))
    deck = DeckSpec(character, tuple(cards), "visible_deck", p["deck_size"] == len(cards))
    mechanics = model.CATALOG.encode_deck(deck)
    identity = model.CATALOG.encode_deck(deck, "identity")
    qualification = {}
    tags = set()
    card_metadata = {}
    for entry in identity["cards"]:
        card = entry["card"]
        identifier = card["spec_ref"]
        spec = model.CATALOG.encode_card_instance(CardInstance(identifier, card["upgrade_level"]))
        qualification[identifier] = spec["qualification"]
        if identifier in static:
            card_metadata[identifier] = static[identifier]
            tags.update("native-var:" + v.lower() for v in static[identifier]["variables"])
            tags.update("keyword:" + v for v in static[identifier]["keywords"])
        else:
            gaps.add("static_card_metadata_missing")
        tags.update("n2e:" + node["kind"] for node in spec["effects"]
                    if node["kind"] != "UnsupportedEffect")
    if any(q != "static_described" for q in qualification.values()):
        gaps.add("card_mechanism_partial")
    if not deck.complete:
        gaps.add("incomplete_deck")
    def powers(rows):
        return [{"id": row["name"], "amount": row["amount"]} for row in rows or []]
    if ([r["name"] for r in p["relics"]] != [r + ".title" for r in resources["relics"]]
            or [r["name"] for r in p["potions"]] != [r + ".title" for r in resources["potions"] if r]):
        gaps.add("inventory_binding_unconfirmed")
    # Bind IDs only when the current game's menu independently shows them.
    visible_inventory = "inventory_binding_unconfirmed" not in gaps
    public = dict(character=character, player={k: p[k] for k in ("hp", "max_hp", "block", "gold")},
                  act=obs["context"]["act"], round=obs["round"], energy=obs["energy"],
                  max_energy=obs["max_energy"], draw_count=obs["draw_pile_count"],
                  discard_count=obs["discard_pile_count"], player_powers=powers(obs.get("player_powers")),
                  relics=resources["relics"] if visible_inventory else [],
                  potions=resources["potions"] if visible_inventory else [],
                  inventory_known=visible_inventory,
                  enemies=[{k: e[k] for k in ("hp", "max_hp", "block")} | {
                      "id": e["name"], "powers": powers(e.get("powers")), "intents": [
                          {k: i[k] for k in ("type", "damage", "hits", "total_damage") if k in i}
                          for i in e.get("intents") or []]} for e in obs["enemies"]],
                  hand=[{k: c[k] for k in ("id", "cost", "type", "can_play", "target_type")} for c in obs["hand"]],
                  identity_deck=identity, mechanics_deck=mechanics, native_card_metadata=card_metadata,
                  candidates=[dict(strategy=s, action_limit=48, active_potions=False) for s in STRATEGIES])
    return public, sorted(gaps), qualification, sorted(tags)


@contextmanager
def root(out, case, versions, deadline, cancelled, memory=None):
    with ls1.b1b.Session(out, deadline, cancelled, memory) as game:
        attest(game, versions)
        began = perf_counter()
        if case["source"] == "synthetic":
            surfaces, timing = ls1.b1b.synth.capture(game, case["spec"])
            public, identity = surfaces["public_root"], surfaces["identity"]
            exact = digest([versions["game_sha256"], surfaces["native"], identity])
            timing.update(game.build_phases)
            grade = "native_constructed"
            yield game, public, identity, exact, grade, timing
        else:
            source = case["restore"]
            pinned = source["root"]
            path, data = bank.checkpoint_bytes(Path(source["bank"]), pinned)
            try:
                public = bank.restore_root(game, pinned, path, game.execute_action)
                identity = pinned["identity"]
                exact = digest([versions["game_sha256"], pinned["checkpoint_sha256"], pinned["entry"], identity])
                timing = dict(handshake_ms=game.startup_ms, initialize_ms=ls1.ms(began))
                yield game, public, identity, exact, "native_cold_restored", timing
            finally:
                if path.read_bytes() != data:
                    raise ValueError("History checkpoint mutated")


def low(game, cap, strategy):
    before = game.request("f1_audit")
    started = perf_counter()
    result = ls1.request(game, "i1_f3b", cap, ls2_trajectory=strategy)
    result.update(search_ms=ls1.ms(started), evidence="prediction_executed",
                  cap=cap, strategy=strategy)
    if before != game.request("f1_audit"):
        raise ValueError("Low-cost label mutated live root")
    terminal = result.get("actions") or []
    result["route_risks"] = ["E3_ENEMY_SIDE_TERMINAL"] if (
        result["status"] == "predicted_win" and terminal and
        ls1.f3b.action_for_wire(terminal[-1])["kind"] == "EndTurn") else []
    return result


def run_cell(game, case, config, profile, public, gaps, versions):
    tier, policy, cap = profile
    if tier == "low":
        outcome = low(game, cap, policy)
        return dict(profile=profile, outcome=outcome, evidence="prediction_executed")
    first = cap // 2
    teacher = policy if tier == "candidate" else None
    outcome = ls1.search(game, first, cap, teacher=teacher, refine=tier == "quality")
    outcome.update(order_changed=False, executed_order_changed=False, candidate_probe=teacher,
                   public_prepare_ms=0.0)
    legacy = ls1_experience(case, versions, public, gaps, "teacher" if teacher else "baseline_search", outcome)
    legacy.pop("model_input")
    return dict(profile=profile, outcome=legacy["outcome"], audit=legacy["audit"],
                evidence="prediction_fixed_replay" if outcome["first_locked"] else "prediction_search")


def execute(out, case, config, profiles, versions, static, deadline, cancelled, memory=None):
    tick = perf_counter()
    item = dict(id=case["id"], source=case["source"], outcome="build_error", cells=[],
                qualification={"root": "unqualified", "solver": "unknown", "encoding": "unknown", "l3": False})
    try:
        with root(out, case, versions, deadline, cancelled, memory) as (game, obs, identity, exact, grade, timing):
            public, gaps, per_card, tags = public_projection(obs, identity["resources"], case["spec"]["character"], static)
            item.update(public=public, exact=exact, live=identity["live"], root_timing=timing, outcome="complete",
                        encoding_gaps=gaps, per_card_qualification=per_card, mechanism_tags=tags)
            item["qualification"].update(root=grade, encoding="partial" if gaps else "described")
            # F3D-B qualified removal of this legacy headless replacement in isolated hosts.
            if any(e["card"]["spec_ref"] == "NEUTRALIZE" for e in public["identity_deck"]["cards"]):
                before = game.request("f1_audit")
                if (game.request("f1_unpatch_neutralize")["method"] != "NeutralizePrefix"
                        or game.request("f1_audit") != before):
                    raise ValueError("Neutralize compatibility changed the source")
                item["compatibility"] = ["F3D-B:NeutralizePrefix"]
            for profile in profiles:
                if cancelled.is_set() or monotonic() >= deadline:
                    raise TimeoutError("Task deadline before next search")
                if profile[0] in ("quality", "candidate") and case["schedule"]["adaptive"] and (
                        item["cells"][0]["outcome"]["status"] == "predicted_win"):
                    continue
                started = perf_counter()
                try:
                    cell = run_cell(game, case, config, profile, public, gaps, versions)
                    cell["wall_ms"] = ls1.ms(started)
                    item["cells"].append(cell)
                except RPC_ERROR as error:
                    if error.status in ("engine_timeout", "engine_crash", "time_limit"):
                        raise
                    # Qualification failures are preserved at this exact budget.
                    status = "unsupported" if "PredictionUnsupported" in str(error) else "rpc_error"
                    item["cells"].append(dict(profile=profile, evidence="unqualified",
                                              outcome=dict(status=status, detail=str(error), transitions=None),
                                              wall_ms=ls1.ms(started)))
            unreliable = {"unsupported", "rpc_error", "root_prediction_mismatch", "verification_failed"}
            item["qualification"]["solver"] = ("partial_or_unsupported" if any(
                c["outcome"]["status"] in unreliable or any(a["status"] == "unsupported"
                    for a in c["outcome"].get("attempts", [])) for c in item["cells"]) else "observed_prediction")
    except DIFFERENCE as error:
        item.update(outcome="root_mismatch", detail=str(error))
    except (RPC_ERROR, *TRANSIENT) as error:
        detail = str(error)
        status = getattr(error, "status", "timeout" if isinstance(error, TimeoutError) else "transport")
        transient = status in ("engine_timeout", "engine_crash", "time_limit", "timeout", "transport")
        item.update(outcome="transient" if transient else status, failure_kind=status, detail=detail)
    item["wall_ms"] = ls1.ms(tick)
    return item
