"""Execute four paired arms with a common Replay envelope and frozen F4 quality policy."""
from time import perf_counter

from spec import GENERATOR, context, digest, edits, feedback, generate
import learning
import engine
from engine import ls1


def proposal(spec, parent=None, operation=None):
    return dict(strategy_spec=spec, strategy_hash=digest(spec), generator_version=GENERATOR,
                parent_strategy=parent, repair_operation=operation, repair_depth=int(parent is not None))


def summarize_trace(actions):
    return [digest(ls1.f3b.action_for_wire(a)) for a in actions]


class Capture:
    """Observe actual legacy attempts without changing their execution or charged Replay."""
    def __init__(self, game):
        self.game = game
        self.paths = []
        self.seed_risk = False

    def request(self, cmd, **kwargs):
        response = self.game.request(cmd, **kwargs)
        if cmd == "i1_f3b" and (s := response.get("search")):
            history = s["history"]
            for route in s["routes"]:
                actions = [history[n]["action"] for n in route["nodes"][1:]]
                self.paths.append(dict(policy=route["plan"]["strategy"], status=route["stop"],
                                       path=summarize_trace(actions), detail=route.get("detail")))
            if s.get("actions"):
                self.seed_risk = ls1.f3b.action_for_wire(s["actions"][-1])["kind"] == "EndTurn"
        return response


def baseline(game, cap):
    observer = Capture(game)
    result = ls1.search(observer, cap//2, cap)
    return dict(status=result["status"], transitions=result["transitions"], wall_ms=result["search_ms"],
                first_replays=(result["first_transitions"] + result["verification_transitions"]
                               if result["first_locked"] else None), first_ms=result["qualified_first_ms"],
                seed_key=result["first_key"], locked_key=result["locked_key"], locked=result["locked"],
                risks=sorted(set(result["route_risks"] + (["E3_ENEMY_SIDE_TERMINAL"] if observer.seed_risk else []))),
                legacy_paths=observer.paths, attempts=[], search_status=result["search_status"],
                quality_status=result["quality_status"], generation_ms=0., repair_ms=0., inference_ms=0.)


def portfolio(game, cap, mode, public, model=None, probe_index=None):
    started = perf_counter()
    ctx = context(public)
    ordered = [proposal(s) for s in generate(ctx)]
    seen = set()
    def unique(rows):
        result = []
        for row in rows:
            key = row["strategy_hash"]
            if key not in seen:
                seen.add(key)
                result.append(row)
        return result

    queue = unique(ordered)
    if probe_index is not None:
        queue = [queue[probe_index % len(queue)]]
    generated = len(ordered)
    duplicates = len(ordered)-len(seen)
    gen_ms = ls1.ms(started)
    infer_ms = repair_ms = 0.
    if mode == "learned":
        t = perf_counter()
        queue = learning.rank(ctx, queue, model)
        infer_ms += ls1.ms(t)
    total = 0
    attempts = []
    out = dict(status="proposals_exhausted", first_replays=None, first_ms=None, locked=None,
               seed_key=None, locked_key=None, risks=[], quality_status=None)
    before = game.request("f1_audit")
    root_stamp = None
    while queue and total < cap//2:
        p = queue.pop(0)
        allocated = min(48, cap//2-total)
        t = perf_counter()
        row = ls1.request(game, "i1_f3b", allocated, strategy_spec=p["strategy_spec"])
        if "root_stamp" not in row:
            out["status"] = row["status"]
            break
        if root_stamp is not None and row["root_stamp"] != root_stamp:
            raise ValueError("Source changed between spec attempts")
        root_stamp = row["root_stamp"]
        total += row["transitions"]
        fb = feedback(row)
        a = p | dict(allocated=allocated, status=row["status"], failure_feedback=fb,
                     trace=row["trace"], path=summarize_trace(row["actions"]), resource=row["resource"],
                     transitions=row["transitions"], wall_ms=ls1.ms(t), route_key=row["route_key"],
                     remaining=row["remaining"], initial_enemy_hp=row["initial_enemy_hp"], risks=[])
        attempts.append(a)
        if row["status"] == "predicted_win":
            actions = [ls1.f3b.action_for_wire(x) for x in row["actions"]]
            verify_start = perf_counter()
            q = ls1.request(game, "i1_f4", cap-total, seed_actions=actions, seed_stamps=row["stamps"],
                            include_history=False)
            total += q["transitions"]
            a.update(verification=q.get("seed_transitions", 0), quality_transitions=q["transitions"]-q.get("seed_transitions", 0))
            out.update(status="verification_failed", quality_status=q["status"])
            if q.get("seed_verified") and q.get("root_stamp") == root_stamp and q["seed_transitions"] == len(actions):
                seed = row["resource"] | dict(key=row["route_key"], at=0, actions=actions)
                eligible = [c for c in q["candidates"] if c["potions"] == seed["potions"]]
                winner = max([seed, *eligible], key=lambda c: (c["hp"], -c["at"]))
                risks = ["E3_ENEMY_SIDE_TERMINAL"] if any(ls1.f3b.action_for_wire(x)["kind"] == "EndTurn"
                    for x in (actions[-1], winner["actions"][-1])) else []
                a.update(status="qualified_win", risks=risks, failure_feedback=None)
                out.update(status="qualified_win", risks=risks, seed_key=seed["key"], locked_key=winner["key"],
                           locked={k: winner[k] for k in (*ls1.RESOURCES, "hp_lost")},
                           first_replays=total-q["transitions"]+len(actions),
                           first_ms=(verify_start-started)*1000+q["seed_lock_ms"])
            else:
                a.update(status="verification_failed", failure_feedback=dict(observed="verification_failed",
                         detail=q.get("detail"), heuristic=[], scope="fixed_route_rebuild"))
            break
        if mode in ("repair", "learned", "probe") and p["repair_depth"] == 0:
            t = perf_counter()
            candidates = [proposal(s, p["strategy_hash"], op) for op, s in edits(p["strategy_spec"], fb, ctx)]
            # Schedule only one bounded edit; leave unscheduled alternatives eligible for future parents.
            generated += len(candidates)
            valid = [child for child in candidates if child["strategy_hash"] not in seen]
            duplicates += len(candidates)-len(valid)
            if valid and mode == "learned":
                tick = perf_counter()
                valid = learning.rank(ctx, valid, model)
                infer_ms += ls1.ms(tick)
            if valid:
                queue.insert(0, valid[0])
                seen.add(valid[0]["strategy_hash"])
            repair_ms += ls1.ms(t)
        if row["status"] in ("wall_cap", "memory_cap"):
            out["status"] = row["status"]
            break
    if out["status"] == "proposals_exhausted" and total >= cap//2:
        out["status"] = "search_budget"
    if total > cap or game.request("f1_audit") != before:
        raise ValueError("Root or budget invariant failed")
    return out | dict(attempts=attempts, transitions=total, wall_ms=ls1.ms(started), generated=generated,
                      duplicates=duplicates, generation_ms=gen_ms, repair_ms=repair_ms, inference_ms=infer_ms)


def execute(out, case, config, profiles, versions, static, deadline, cancelled, memory=None):
    started = perf_counter()
    item = dict(outcome="build_error", cells=[], id=case["id"])
    try:
        with engine.root(out, case, versions, deadline, cancelled, memory) as (game, obs, ident, exact, grade, timing):
            t = perf_counter()
            public, gaps, _, _ = engine.public_projection(obs, ident["resources"], case["spec"]["character"], static)
            public.pop("candidates")
            prepare_ms = ls1.ms(t)
            if "NEUTRALIZE" in {c["card"]["spec_ref"] for c in public["identity_deck"]["cards"]}:
                state = game.request("f1_audit")
                if game.request("f1_unpatch_neutralize")["method"] != "NeutralizePrefix" or state != game.request("f1_audit"):
                    raise ValueError("Unpatch affected source")
            item.update(exact=exact, grade=grade, public=public, gaps=gaps, timing=timing, outcome="complete",
                        evidence="research_exact_prediction", source=case["source"], public_prepare_ms=prepare_ms)
            for mode, index, cap in profiles:
                t = perf_counter()
                try:
                    if mode == "legacy_probe":
                        path = engine.low(game, cap, index)
                        result = dict(status=path["status"], detail=path.get("detail"), attempts=[],
                                      path=summarize_trace(path.get("actions", [])), first_ms=None,
                                      transitions=path["transitions"])
                    elif mode == "baseline":
                        result = baseline(game, cap)
                    else:
                        result = portfolio(game, cap, mode, public, config.get("model"), index)
                    # End-to-end cell wall includes wire, auditing and the public encoding if used.
                    extra = 0 if mode in ("baseline", "legacy_probe") else prepare_ms
                    result["wall_ms"] = ls1.ms(t)+extra
                    if result["first_ms"] is not None:
                        result["first_ms"] += extra
                except engine.RPC_ERROR as error:
                    if error.status in ("engine_timeout", "engine_crash", "time_limit"):
                        raise
                    result = dict(status="rpc_error", detail=str(error), transitions=None, wall_ms=ls1.ms(t), attempts=[])
                item["cells"].append(dict(profile=[mode, index, cap], outcome=result))
    except engine.DIFFERENCE as e:
        item.update(outcome="root_mismatch", detail=str(e))
    except (engine.RPC_ERROR, *engine.TRANSIENT) as e:
        status = getattr(e, "status", "transport")
        item.update(outcome="transient" if status in ("engine_timeout","engine_crash","time_limit","transport")
                    else status, detail=str(e))
    item["wall_ms"] = ls1.ms(started)
    return item
