"""Public deterministic witnesses, policy-conditioned scoring, and execution checks."""
from collections import Counter, deque
from dataclasses import dataclass
from time import perf_counter

import torch

from loop_common import checksum, digest
from sv_data import Encoder
from sv_model import load
from sv_runtime import tensors

UTILITY = "death=-1;win=1+.25*hp/terminal_max"
MOVES = {"end_turn", "play_card"}


@dataclass(frozen=True)
class Step:
    node: int
    observation: dict
    index: int


def legal_edge(observation, move):
    index = move.get("index")
    menu = observation["actions"]
    if (not isinstance(index, int) or not 0 <= index < len(menu)
            or menu[index]["index"] != index or menu[index]["kind"] != move["kind"]):
        raise ValueError("Graph move does not match the public legal menu")
    if move["kind"] == "play_card" and observation["hand"][menu[index]["card"]]["id"] != move["card"]:
        raise ValueError("Graph move no longer refers to the same card instance slot")
    return index


def extract(graph, project, encoder, public, memory):
    """Extract executable paths without consulting simulation keys or grouped hidden outcomes."""
    if graph.get("type") != "sv4a_public_graph":
        raise ValueError("Expected public SV4A wire")
    observations = {int(index): project(wire) for index, wire in graph["observations"].items()}
    if observations.get(0) != public:
        raise ValueError("Search root observation differs from the executing episode")
    incoming = {}
    for edge in graph["edges"]:
        if edge["to"] in incoming or edge["from"] >= edge["to"]:
            raise ValueError("Expected one forward parent in the unmerged public tree")
        incoming[edge["to"]] = edge
    routes, histories = {0: ()}, {0: memory}
    for node in sorted(observations):
        if node == 0:
            continue
        edge = incoming[node]
        parent, move = edge["from"], edge["action"]
        if parent not in routes or move["kind"] not in MOVES:
            continue
        observation = observations[parent]
        index = legal_edge(observation, move)
        routes[node] = (*routes[parent], Step(parent, observation, index))
        histories[node] = encoder.update(histories[parent], observation, observation["actions"][index])
    boundaries, unscored = [], Counter()
    for item in graph["boundaries"]:
        kind = item["kind"]
        if kind not in ("end_play_a", "random", "victory", "death"):
            unscored[kind] += 1
            continue
        edge = incoming[item["id"]]
        if edge["action"]["kind"] == "settle_turn":
            edge = incoming[edge["from"]]
        parent, move = edge["from"], edge["action"]
        if parent not in routes or move["kind"] not in MOVES:
            unscored["choice_or_unverified_path"] += 1
            continue
        observation = observations[parent]
        index = legal_edge(observation, move)
        steps = (*routes[parent], Step(parent, observation, index))
        boundaries.append((item, steps))
    return observations, histories, boundaries, unscored


class NetworkPolicy:
    def __init__(self, weights, continuation, budget, epsilon, host_id, cfg):
        self.net, saved = load(weights)
        self.encoder = Encoder(saved["vocabulary"])
        if continuation not in saved["policies"]:
            raise ValueError("The requested continuation has no trained policy slot")
        self.slot = saved["policies"].index(continuation)
        self.cfg = cfg
        self.budget, self.epsilon = budget, epsilon
        self.definition = dict(version=cfg["version"], model=checksum(weights), continuation=continuation,
            host=host_id, search="sv1.public.tree" if budget else None, budget=budget,
            depth=cfg["search_depth"] if budget else None, wall_ms=cfg["search_wall_ms"] if budget else None,
            direct_stop_margin=cfg["direct_stop_margin"], utility=UTILITY,
            fallback="all-legal-direct-q", exploration=f"uniform-legal-mixture:{epsilon}",
            sampling="stable-argmax-with-exact-epsilon-conditional-probability")
        self.identity = digest(self.definition)

    @torch.inference_mode()
    def forward(self, requests):
        """Batch all legal actions for each public state exactly once."""
        rows = [row for (block,) in requests for row in block]
        result = []
        for offset in range(0, len(rows), 128):
            chunk = rows[offset:offset + 128]
            batch = tensors(chunk, "cpu")
            _, output = self.net(batch)
            probability = self.net.probabilities(output)
            utility = self.net.utility(probability)
            for row, prob, value in zip(chunk, probability.numpy(), utility.numpy(), strict=True):
                size = len(row["actions"])
                result.append((value[:size], prob[:size]))
        start = 0
        for block, in requests:
            yield result[start:start + len(block)]
            start += len(block)


class BattlePolicy:
    def __init__(self, model, project, forward, rng, forced=None):
        self.model, self.project, self.forward, self.rng = model, project, forward, rng
        self.history = model.encoder.initial_history()
        self.plan = deque()
        self.predicted_end = None
        self.previous_end = None
        self.trace, self.timing, self.counts = [], Counter(), Counter()
        self.forced = forced

    def score(self, observations):
        start = perf_counter()
        rows = [self.model.encoder.encode(observation, history) | {"policy": self.model.slot}
                for observation, history in observations]
        self.timing["encode"] += perf_counter() - start
        start = perf_counter()
        result = self.forward(rows)
        self.timing["inference"] += perf_counter() - start
        self.counts["evaluated_states"] += len(rows)
        self.counts["scoring_requests"] += 1
        return result

    def search(self, public, lane, position):
        host = self.model
        start = perf_counter()
        graph = lane.request("i1_sv1_graph", mode="tree", public_run=True, transitions=host.budget,
            wall_ms=host.cfg["search_wall_ms"], depth=host.cfg["search_depth"], memory_bytes=512 * 2**20)
        self.timing["graph_rpc"] += perf_counter() - start
        self.timing["solver"] += graph["solver_ms"] / 1000
        self.counts.update(searches=1, transitions=graph["transitions"], nodes=graph["nodes"],
                           boundaries=len(graph["boundaries"]))
        self.counts.update(f"boundary_{item['kind']}" for item in graph["boundaries"])
        stop = graph.get("stop") or "exhausted"
        self.counts[f"stop_{stop}"] += 1
        if stop in ("wall_cap", "managed_memory_cap"):
            return None, "resource_fault"
        observations, histories, ends, skipped = extract(
            graph, self.project, host.encoder, public, self.history)
        self.counts.update({"unscored_" + key: n for key, n in skipped.items()})
        nodes = [0, *sorted({path[-1].node for item, path in ends
                            if item["kind"] in ("end_play_a", "random")} - {0})]
        scores = dict(zip(nodes, self.score([(observations[node], histories[node]) for node in nodes]), strict=True))
        root_scores = scores[0][0]
        direct = int(root_scores.argmax())
        priority = None
        best_by_first = {}
        for item, path in ends:
            kind = item["kind"]
            probability = None
            if kind in ("victory", "death"):
                terminal = item["public"]
                score = -1. if kind == "death" else 1 + .25 * terminal["hp"] / terminal["max_hp"]
            else:
                last = path[-1]
                values, probs = scores[last.node]
                score = float(values[last.index])
                probability = probs[last.index]
            first = path[0].index
            best_by_first[first] = max(score, best_by_first.get(first, -2))
            key = (score, -len(path), -first, -item["id"])
            if priority is None or key > priority[0]:
                priority = (key, (item, path, probability))
        self.trace.append(dict(position=position, nodes=graph["nodes"], states=len(nodes), stop=stop,
            transitions=graph["transitions"], scored=len(ends), unscored=dict(skipped),
            direct=direct, direct_value=float(root_scores[direct]), by_first=best_by_first))
        if priority is not None and priority[0][0] > root_scores[direct] + host.cfg["direct_stop_margin"]:
            item, path, probability = priority[1]
            self.plan.extend(path)
            self.predicted_end = item
            self.trace[-1].update(chosen=path[0].index, path=[step.index for step in path],
                                  boundary=item["kind"], reason=item.get("reason"), utility=priority[0][0],
                                  probability=probability.tolist() if probability is not None else None)
            self.counts["plans"] += 1
            self.counts["planned_actions"] += len(path)
            return self.plan[0].index, "plan"
        self.counts["direct_stop"] += 1
        return direct, "direct_stop"

    def act(self, public, lane, position):
        if self.plan and self.plan[0].observation != public:
            self.counts["public_mismatch"] += 1
            self.plan.clear()
            self.predicted_end = None
        if self.plan:
            index, mode = self.plan[0].index, "plan"
        else:
            index, mode = None, "direct"
            if self.model.budget and public["decision"]["phase"] == "combat":
                try:
                    index, mode = self.search(public, lane, position)
                except ValueError as error:
                    self.counts["wire_or_root_mismatch"] += 1
                    self.trace.append(dict(position=position, fallback=str(error)))
                    mode = "unqualified_graph"
            elif self.model.budget:
                mode = "pending_choice"
            if index is None:
                index = int(self.score([(public, self.history)])[0][0].argmax())
                if self.model.budget:
                    self.counts["fallback_" + mode] += 1
        if self.forced is not None and position == 0:
            eligible = [a["index"] for a in public["actions"] if
                        (self.forced == "Cascade" and a["kind"] == "play_card"
                         and public["hand"][a["card"]]["id"] == "CASCADE")
                        or (self.forced == "EndTurn" and a["kind"] == "end_turn")]
            if not eligible:
                raise ValueError("Forced diagnostic action is absent")
            index, mode = eligible[0], "diagnostic"
            self.plan.clear()
            self.predicted_end = None
        n = len(public["actions"])
        greedy = index
        epsilon = self.model.epsilon
        if epsilon and self.rng.random() < epsilon:
            self.counts["explore_draw"] += 1
            index = self.rng.randrange(n)
        predicted = None
        if index != greedy:
            self.counts["explore_changed"] += 1
            self.plan.clear()
            self.predicted_end = None
            mode = "exploration"
        elif self.plan:
            self.plan.popleft()
            self.counts["executed_plan_steps"] += 1
            if not self.plan:
                predicted, self.predicted_end = self.predicted_end, None
        action = public["actions"][index]
        self.history = self.model.encoder.update(self.history, public, action)
        self.previous_end = predicted
        probability = epsilon / n + (1 - epsilon if index == greedy else 0.)
        return index, probability, mode

    def after(self, state):
        status = state["status"]
        item = self.previous_end
        self.previous_end = None
        if self.plan and status != "active":
            self.counts["unexpected_prefix_end"] += 1
            self.plan.clear()
            self.predicted_end = None
        if item is None:
            return
        if item["kind"] == "random":
            self.counts["executed_random_trigger"] += 1
            if status == "active":
                self.counts["replan_after_random"] += 1
        if item["kind"] in ("victory", "death"):
            expected = "predicted_win" if item["kind"] == "victory" else "death"
            terminal = state.get("terminal_observation")
            if (status != expected or terminal is None or
                    any(terminal[field] != item["public"][field] for field in ("hp", "max_hp"))):
                self.counts["terminal_mismatch"] += 1
            else:
                self.counts["terminal_verified"] += 1
