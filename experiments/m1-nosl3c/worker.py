"""Bounded worker sessions, public decisions and isolated native retirement."""
from contextlib import ExitStack
from hashlib import sha256
import random
import runpy
from time import monotonic, perf_counter, time_ns

import torch

from protocol import DATA_VERSION, HERE, MODEL_VERSION, digest, policy_seed
from nosl3b_episode import baseline, choose, coverage
from nosl_experience import TRANSITION, json_bytes, public_observation, save_json, terminal
from nosl_model import CATALOG, Decision, WIDTH


class InvariantError(ValueError):
    pass


def ms(start):
    return (perf_counter() - start) * 1000


class Environment:
    def __init__(self, output):
        self.output = output
        s3a = self.s3a = runpy.run_path(str(HERE.parent / "m1-s3a/produce.py"))
        s3a["solver_binding"].__globals__["HOST"] = "m1-nosl3c-build"
        self.versions = s3a["solver_binding"](output, s3a["FROZEN"], None)
        self.b1b = s3a["b1b"]
        self.errors = (self.b1b.bank.f1.i2.StopRun, TimeoutError, OSError, RuntimeError)
        self.versions.update(model=MODEL_VERSION, catalog=CATALOG.content_sha256, torch=str(torch.__version__))
        if self.versions["game_sha256"] != CATALOG.rule_version:
            raise InvariantError("Game version differs from governed card semantics")


def verify_resources(obs):
    if obs["relics"] or any(obs["potions"]) or any(a["kind"] == "use_potion" for a in obs["actions"]):
        raise InvariantError("Nonempty active resources in no-resource public observation")


class DecisionCache:
    """Root-local immutable tensors keyed by the exact public DTO."""
    def __init__(self, capacity):
        self.capacity = capacity
        self.rows = {}
        self.hits = 0

    def get(self, obs):
        if not self.capacity:
            return Decision(obs)
        key = json_bytes(obs)
        if key in self.rows:
            self.hits += 1
            return self.rows[key]
        result = Decision(obs)
        if len(self.rows) < self.capacity:
            self.rows[key] = result
        return result


def new_record(env, config, item, stage, model_hash, mode, replicate, cold):
    seed = policy_seed(config, item, mode, replicate, stage)
    row = baseline.record(item, "mechanism", model_hash, env.versions, seed, stage)
    row.update(experiment=DATA_VERSION, model_version=MODEL_VERSION, mode=mode, replicate=replicate,
               initialization=config["initialization_seed"], pressure=item["pressure"], stocked=False,
               missing_cards=coverage(item), cold_first=cold, inference_ms=[], transitions=[])
    row["behavior"]["kind"] = mode
    return row


@torch.no_grad()
def rollout(game, config, row, policy, cache, trace):
    started = perf_counter()
    reset = game.request("i1_n2_reset", arm="A", cap=config["action_cap"], potions=False, rejected=[])
    if "episode" not in reset:
        raise InvariantError("Root prediction does not match its native source")
    reset_ms = ms(started)
    state = reset["episode"]
    history = torch.zeros(WIDTH)
    rng = random.Random(row["behavior"]["seed"])
    steps = row["transitions"]
    phases = dict(features_ms=0., forward_ms=0., memory_choice_ms=0., rpc_ms=0.)
    while state["status"] == "active":
        obs = public_observation(state["observation"])
        verify_resources(obs)
        tick = perf_counter()
        decision = cache.get(obs)
        phases["features_ms"] += ms(tick)
        infer = perf_counter()
        logits, value, embedding, actions = policy(decision, history)
        if not (torch.isfinite(logits).all() and torch.isfinite(value).all()):
            raise FloatingPointError("Nonfinite inference")
        phases["forward_ms"] += ms(infer)
        choose_started = perf_counter()
        logp = logits.log_softmax(0)
        i, lp = choose(logits, row["mode"], rng, decision.actions)
        top = int(logits.argmax())
        history = policy.remember(history, embedding, actions[i])
        phases["memory_choice_ms"] += ms(choose_started)
        row["inference_ms"].append(ms(tick))
        action = decision.actions[i]
        position = state["actions"]
        step = dict(schema=TRANSITION, position=position, observation=obs,
                    action=action, behavior_logp=lp, policy_logp=logp.tolist(), policy_argmax=top,
                    value=value.tolist(), next_observation=None, advanced=False)
        steps.append(step)
        tick = perf_counter()
        state = game.request("i1_n2_step", position=position, index=action["index"])["episode"]
        phases["rpc_ms"] += ms(tick)
        trace.append({k: state.get(k) for k in ("audit_action", "audit_stamp", "detail")})
        step["advanced"] = state.get("actions", 0) == position + 1
        if state["status"] == "invalid_action" or (state["status"] == "active" and not step["advanced"]):
            raise InvariantError("Prediction rejected its own legal action")
        if state["status"] == "active":
            step["next_observation"] = public_observation(state["observation"])
    result = terminal(state, steps[-1]["action"] if steps else None)
    if result["observation"] and any(result["observation"]["potions"]):
        raise InvariantError("Nonempty terminal potion inventory")
    if steps and steps[-1]["advanced"]:
        steps[-1]["next_observation"] = result["observation"]
    tick = perf_counter()
    game.request("i1_n2_close")
    row.update(feedback=result, rollout_ms=ms(started), prepare_ms=reset.get("root_prepare_ms"),
               timing=dict(**phases, reset_ms=reset_ms, close_ms=ms(tick),
                           engine_advance_ms=state.get("advance_ms", 0.),
                           engine_replay_ms=state.get("replay_ms", 0.),
                           engine_observe_ms=state.get("observe_ms", 0.)))
    trace.append(dict(status=state["status"], detail=state.get("detail"), result=state.get("result")))


class Worker:
    def __init__(self, env, config, resident, cache=True):
        self.env, self.config, self.resident = env, config, resident
        self.cache = cache
        self.stack = self.game = None
        self.count = 0

    def close(self):
        if self.stack is not None:
            self.stack.close()
            self.stack = self.game = None

    def start(self):
        self.stack = ExitStack()
        try:
            self.game, _ = self.env.s3a["attested"](self.env.output, self.stack, self.env.versions)
        except BaseException:
            self.close()
            raise
        self.count = 0

    def retire(self, row, trace):
        game = self.game
        # A qualifying sampled win is used solely to settle this private process.
        # Exact native prefix verification is the admission check for reusing it.
        game.teacher_frames, game.teacher_choices = [], []
        game.request("i1_begin")
        for i, (step, raw) in enumerate(zip(row["transitions"], trace[:-1], strict=True)):
            action = dict(raw["audit_action"])
            if isinstance(action["kind"], int):
                action["kind"] = ("PlayCard", "UsePotion", "EndTurn")[action["kind"]]
            chosen = step["action"]
            if chosen["choice"] is not None and sum(
                    a["card"] == chosen["card"] for a in step["observation"]["actions"]) == 1:
                action.pop("choice")
            reply = game.request("i1_step", action=action)
            if reply["type"] != "i1_state" or not reply.get("state"):
                return f"native_rejected_at_{i}"
            continuation = reply["state"][0]["exact_continuation_state"]
            if sha256(continuation.encode()).hexdigest() != raw["audit_stamp"]:
                return f"native_stamp_difference_at_{i}"
        if not reply["terminal"] or reply["decision"]["decision"] != "card_reward":
            return "native_map_boundary_unavailable"
        if game.request("action", action="skip_card_reward")["decision"] != "map_select":
            return "native_reward_boundary_unavailable"
        game.request("i1_release")
        game.request("f1_3c_release")
        if game.request("b1a_reset")["type"] != "reset":
            raise InvariantError("Settled reset failed")
        initial = game.request("b1b_initial_profile")["value"]
        if game.request("b1a_profile")["value"] != initial:
            raise InvariantError("Resident worker did not restore progress baseline")
        return "admitted"

    def attempt(self, item, stage, model_hash, policy, modes):
        started = perf_counter()
        expired = self.game is not None and self.game.deadline - monotonic() < 20
        if expired:
            self.close()
        cold = self.game is None
        rows = [new_record(self.env, self.config, item, stage, model_hash, mode, rep, cold)
                for mode, rep in modes]
        audit = dict(spec=item["spec"], traces=[[] for _ in rows])
        timing = dict(startup_ms=0., handshake_ms=0., initialize_ms=0., snapshot_ms=0.,
                      resident=not cold, lease_recycled=expired, retirement="cold_only" if not self.resident else "not_attempted")
        phase = "root"
        try:
            if cold:
                tick = perf_counter()
                self.start()
                timing["startup_ms"] = ms(tick)
                timing["handshake_ms"] = self.game.startup_ms
            game = self.game
            native, build = self.env.b1b.synth.capture(game, item["spec"])
            self.count += 1
            timing.update(initialize_ms=build["initialize_ms"], snapshot_ms=build["snapshot_ms"],
                          build_phases=game.build_phases)
            audit["exact_root_sha256"] = digest(native)
            if any(native["identity"]["resources"]["potions"]) or native["identity"]["resources"]["relics"]:
                raise InvariantError("Native inventory violates resource-free protocol")
            before = game.request("f1_audit")
            phase = "rollout"
            cache = DecisionCache(self.config["decision_cache"] if self.cache else 0)
            for row, trace in zip(rows, audit["traces"], strict=True):
                rollout(game, self.config, row, policy, cache, trace)
            timing["cache_hits"] = cache.hits
            if game.request("f1_audit") != before:
                raise InvariantError("Prediction mutated its source player or RNG")
            if self.resident and self.count < self.config["worker_root_limit"]:
                qualified = next((i for i, r in enumerate(rows) if r["feedback"]["status"] == "predicted_win"), None)
                if qualified is not None:
                    phase = "retire"
                    tick = perf_counter()
                    timing["retirement"] = self.retire(rows[qualified], audit["traces"][qualified])
                    timing["retirement_ms"] = ms(tick)
                else:
                    timing["retirement"] = "no_admissible_win"
        except (InvariantError, FloatingPointError, self.env.b1b.synth.f3a.Difference) as error:
            audit["fatal"] = dict(phase=phase, detail=str(error))
            save_json(self.env.output / "audit-only" / f"invariant-{item['id']}-{time_ns()}.json.gz",
                      audit, compress=True)
            raise
        except self.env.errors as error:
            audit["fault"] = dict(phase=phase, type=type(error).__name__, detail=str(error))
            status = baseline.failed(error)
            if phase == "root":
                status = dict(status="error", public_reason="root_generation_failed")
            if phase == "retire":
                timing["retirement"] = "native_retirement_fault"
            for row in rows:
                if "feedback" not in row:
                    n = row["transitions"]
                    row["feedback"] = terminal(status | dict(actions=sum(s["advanced"] for s in n),
                                                              transitions=len(n)), None)
        finally:
            if timing["retirement"] != "admitted":
                self.close()
        timing["total_ms"] = ms(started)
        for row in rows:
            row["total_ms"] = timing["total_ms"]
        return dict(root=item["id"], rows=rows, timing=timing), audit