"""Instrument the unchanged reference optimizer, anchored to its source statements."""
from functools import wraps
from inspect import getsource

from optimizer import Times
from learning import train as reference


def replace(source, original, replacement):
    if source.count(original) != 1:
        raise RuntimeError(f"Frozen measurement boundary changed: {original}")
    return source.replace(original, replacement)


def make_train(times, witness):
    def measured(name, func, *args, **kwargs):
        tick = times.start()
        try:
            return func(*args, **kwargs)
        finally:
            times.end(name, tick)

    source = getsource(reference)
    pairs = (
        ('d = Decision(step["observation"])', 'd = measured("features", Decision, step["observation"])'),
        ('= policy(d, memory)', '= measured("forward_logits", policy, d, memory)'),
        ('logp = logits.log_softmax(0)', 'tick = times.start()\n            logp = logits.log_softmax(0)'),
        ('memory = policy.remember(memory, state, actions[chosen])',
         'times.end("loss_graph", tick)\n            if witness is not None:\n'
         '                witness.append((value.detach().clone(), logp.detach().clone()))\n'
         '            memory = measured("history_gru", policy.remember, memory, state, actions[chosen])'),
        ('torch.autograd.grad(a, tuple(policy.actor.parameters()), retain_graph=True)',
         'measured("actor_diagnostic_grad", torch.autograd.grad, a, tuple(policy.actor.parameters()), retain_graph=True)'),
        ('loss.backward()', 'measured("joint_backward", loss.backward)'),
        ('g = torch.nn.utils.clip_grad_norm_', 'if witness is not None:\n'
         '        witness.gradients.update({k: p.grad.detach().clone() for k, p in policy.named_parameters() if p.grad is not None})\n'
         '    g = torch.nn.utils.clip_grad_norm_'),
        ('optimizer.step()', 'measured("adam", optimizer.step)'),
    )
    for original, replacement in pairs:
        source = replace(source, original, replacement)
    scope = reference.__globals__ | dict(measured=measured, times=times, witness=witness)
    exec(compile(source, reference.__code__.co_filename, "exec"), scope)
    return scope["train"]


@wraps(reference)
def train(*args, witness=None, **kwargs):
    times = Times()
    start = times.start()
    result = make_train(times, witness)(*args, **kwargs)
    return result | dict(phases_s=times.wall, phases_cpu_s=times.cpu, cpu_seconds=times.start()[1] - start[1])