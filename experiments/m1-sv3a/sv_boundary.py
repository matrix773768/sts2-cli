"""Read the optional SV1 public graph export and batch-evaluate stable boundaries."""
from dataclasses import dataclass

import numpy as np
import torch

from sv_data import Encoder
from sv_runtime import tensors
from sv_model import load


@dataclass(frozen=True)
class Boundary:
    node: int
    kind: str
    observation: dict | None = None
    action: dict | None = None
    history: np.ndarray | None = None
    terminal: dict | None = None
    fallback: str | None = None


def contexts(result, project, encoder, root_history):
    if result.get("oracle"):
        raise ValueError("Oracle graph is ineligible for NOSL value scoring")
    graph = result["graph"]
    observations = {int(index): project(value) for index, value in graph.get("public_decisions", {}).items()}
    edges = {}
    for edge in graph["edges"]:
        edges.setdefault(edge["from"], []).append(edge)
    for endpoint in graph["endpoints"]:
        outcome = endpoint["outcome"]
        node, kind = endpoint["node"], outcome["kind"]
        if kind in ("victory", "death"):
            yield Boundary(node, kind, terminal=outcome["public"]["state"])
            continue
        if kind not in ("end_play_a", "random"):
            yield Boundary(node, kind, fallback=kind)
            continue
        stable, memory = 0, root_history
        action = None
        witness = endpoint["witness"]
        # The synthetic settle edge continues an EndTurn just issued at A.
        if witness and witness[-1]["kind"] == "settle_turn":
            witness = witness[:-1]
        for position, move in enumerate(witness):
            observation = observations.get(stable)
            if observation is None or move["kind"] not in ("end_turn", "play_card"):
                action = None
                break
            index = move.get("index")
            if not isinstance(index, int) or not 0 <= index < len(observation["actions"]):
                raise ValueError("Missing legal action index in SV1 witness")
            action = observation["actions"][index]
            if action["kind"] != move["kind"]:
                raise ValueError("SV1 action no longer matches the public menu")
            if position != len(witness) - 1:
                matching = [edge for edge in edges[stable] if edge["action"] == move]
                if len(matching) != 1:
                    raise ValueError("Ambiguous witness action")
                stable = matching[0]["to"]
                memory = encoder.update(memory, observation, action)
        if action is None:
            yield Boundary(node, kind, fallback="needs_public_choice_or_stable_observation")
        else:
            yield Boundary(node, kind, observation=observation, action=action, history=memory)


class BoundaryScorer:
    def __init__(self, checkpoint, policy_key, device="cpu"):
        self.model, saved = load(checkpoint, device)
        self.encoder = Encoder(saved["vocabulary"])
        self.policy = saved["policies"].index(policy_key)
        self.device = device

    @torch.inference_mode()
    def evaluate(self, items, batch_size=256):
        results, waiting = {}, []
        for item in items:
            if item.terminal is not None:
                hp, maximum = item.terminal["hp"], item.terminal["max_hp"]
                results[item.node] = dict(source="terminal", hp=hp, max_hp=maximum,
                    utility=-1. if item.kind == "death" else 1. + .25 * hp / maximum)
            elif item.fallback:
                results[item.node] = dict(source="actor_fallback", reason=item.fallback)
            else:
                index = item.action["index"]
                if item.observation["actions"][index] != item.action:
                    raise ValueError("Boundary trigger is outside the public legal menu")
                waiting.append((item, self.encoder.encode(item.observation, item.history) |
                                dict(policy=self.policy, chosen=index)))
        for offset in range(0, len(waiting), batch_size):
            chunk = waiting[offset:offset+batch_size]
            batch = tensors([row for _, row in chunk], self.device)
            _, q = self.model(batch, chosen_only=True)
            probabilities = self.model.probabilities(q)
            utilities = self.model.utility(probabilities)
            for (item, _), prob, score in zip(chunk, probabilities.tolist(), utilities.tolist(), strict=True):
                results[item.node] = dict(source="q", kind=item.kind, utility=score, probability=prob,
                                          action=item.action["kind"], index=item.action["index"])
        return results


@torch.inference_mode()
def fallback_action(actor, observation, history):
    """Use the frozen Actor at the actual public decision when no boundary qualifies."""
    from evaluate import Decision
    logits, *_ = actor(Decision(observation), history)
    return observation["actions"][int(logits.argmax())]
