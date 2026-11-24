"""Execute only public deterministic prefixes and score their boundaries in DC2B units."""
from functools import partial
from time import perf_counter
from types import FunctionType

from value import Path, checksum, expected, load, payoff, torch
from dc_common import digest
import loop_battle
from loop_policy import BattlePolicy, extract
from sv_data import Encoder
from sv_runtime import tensors


class Policy:
    def __init__(self, weights, continuation, budget, epsilon, host_id, cfg):
        self.net, saved = load(weights)
        self.encoder = Encoder(saved["vocabulary"])
        self.slot = saved["policies"].index(continuation)
        self.budget, self.epsilon, self.cfg = budget, epsilon, cfg
        self.definition = dict(host=host_id, model=checksum(weights), continuation=continuation,
                               budget=budget, epsilon=epsilon, depth=cfg["search_depth"],
                               wall_ms=cfg["search_wall_ms"], margin=cfg["direct_stop_margin"],
                               source=checksum(Path(__file__)), value=checksum(Path(__file__).with_name("value.py")))
        self.identity = digest(self.definition)

    @torch.inference_mode()
    def forward(self, requests):
        for (rows,) in requests:
            batch = tensors(rows,"cpu")
            probability=self.net(batch)[1].softmax(-1)
            context=probability.new_tensor([r["dc_hp"] for r in rows])
            scores=expected(probability,*(context[:,i,None] for i in range(3)))
            yield [(s[:len(r["actions"])].numpy(),p[:len(r["actions"])].numpy())
                   for r,s,p in zip(rows,scores,probability,strict=True)]


class Controller(BattlePolicy):
    def act(self, public, lane, position):
        if position==0:
            self.initial_hp,self.initial_max=public["hp"],public["max_hp"]
        return super().act(public,lane,position)

    def score(self, observations):
        rows=[self.model.encoder.encode(o,h) | dict(policy=self.model.slot,
               dc_hp=(self.initial_hp,o["hp"],self.initial_max)) for o,h in observations]
        return self.forward(rows)

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
                score = -50. if kind == "death" else float(payoff(
                    torch.tensor(self.initial_hp-terminal["hp"]),torch.tensor(self.initial_max)))
            else:
                last = path[-1]
                values, probs = scores[last.node]
                score = float(values[last.index])
                probability = probs[last.index]
            first = path[0].index
            best_by_first[first] = max(score, best_by_first.get(first, -float("inf")))
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


def run(*args, **kwargs):
    runner=FunctionType(loop_battle.run.__code__,loop_battle.run.__globals__ |
                        {"NetworkPolicy":Policy,"BattlePolicy":Controller},
                        argdefs=loop_battle.run.__defaults__)
    return runner(*args,**kwargs)
