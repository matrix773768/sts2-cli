"""Batch all legal actions once and adapt the scorer to existing evaluation lanes."""
from threading import local
from time import perf_counter

import torch

from sv_data import Encoder, checksum, collate, digest
from sv_model import load
from features import SOURCE_HASHES
from train import load_policy


def tensors(rows, device):
    return {key: torch.from_numpy(value).to(device) for key, value in collate(rows).items()}


@torch.inference_mode()
def score_public(model, encoder, decisions):
    """Return V and every legal Q distribution for (observation, history, policy slot) requests."""
    if not decisions:
        return []
    device = model.fractions.device
    batch = tensors([encoder.encode(obs, history) | {"policy": policy}
                     for obs, history, policy in decisions], device)
    state, actions = model(batch)
    v, q = model.probabilities(state).tolist(), model.probabilities(actions).tolist()
    return [dict(v=v[i], q=[dict(action=action, probability=q[i][j])
                           for j, action in enumerate(obs["actions"])])
            for i, (obs, _, _) in enumerate(decisions)]


class ValueActor:
    def __init__(self, checkpoint, prior, top_k, constrained=False):
        self.model, contract = load(checkpoint)
        installed, vocab = load_policy(prior)
        self.prior = installed
        if vocab != contract["vocabulary"]:
            raise ValueError("Behavior prior and value vocabulary differ")
        self.encoder = Encoder(vocab)
        self.condition = contract["policies"].index(f"nosl3c.hp-loss-actor-critic.v4|{SOURCE_HASHES[1]}|sample")
        self.top_k = top_k
        self.constrained = constrained
        self.costs = local()
        self.identity = digest(dict(value=checksum(checkpoint), condition=self.condition,
            prior=checksum(prior) if constrained else None, top_k=top_k if constrained else None,
            selection="risk_neutral_expected_utility_v1"))

    @torch.inference_mode()
    def __call__(self, decision, history):
        start = perf_counter()
        memory = history.numpy() if isinstance(history, torch.Tensor) else history
        observation = decision.obs
        features = self.encoder.encode(observation, memory)
        batch = tensors([features | {"policy": self.condition}], "cpu")
        encoded = perf_counter()
        _, values = self.model(batch)
        distributions = self.model.probabilities(values)[0]
        utility = self.model.utility(distributions)
        behavior = self.prior(batch)[0].softmax(-1)
        allowed = behavior.argsort(descending=True, stable=True)[:self.top_k]
        unrestricted = int(utility.argmax())
        selected = int(allowed[utility[allowed].argmax()]) if self.constrained else unrestricted
        self.costs.measure.append((encoded - start, perf_counter() - encoded))
        self.costs.diagnostics.append(dict(prior=float(behavior[selected]), death=float(distributions[selected, 0]),
            advantage=float(utility[selected] - utility[allowed[0]]), greedy_outside_prior=unrestricted not in allowed.tolist()))
        # The historical sampler requires finite log probabilities for every entry.
        # The exponent of -1e6 underflows, so only the greedy selection has mass.
        logits = torch.full_like(utility, -1e6)
        logits[selected] = 0.
        return logits, logits.new_zeros(()), observation, decision.actions

    def remember(self, history, observation, action):
        memory = history.numpy() if isinstance(history, torch.Tensor) else history
        return self.encoder.update(memory, observation, action)
