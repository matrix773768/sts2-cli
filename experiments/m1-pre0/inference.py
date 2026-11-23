"""Bounded cross-lane inference using the same frozen v4 forward function."""
from concurrent.futures import Future
from queue import Empty, Queue
from threading import Thread
from time import perf_counter

import torch
from batched import forward


class Inference:
    def __init__(self, policy, size, delay=0.001):
        self.policy, self.size, self.delay = policy, size, delay
        self.queue = Queue(maxsize=size * 2)
        self.thread = Thread(target=self.run, name="v4-inference")

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.queue.put(None)
        self.thread.join()

    def __call__(self, decision, history):
        reply = Future()
        self.queue.put((decision, history, reply))
        return reply.result()

    @torch.inference_mode()
    def run(self):
        while (first := self.queue.get()) is not None:
            requests = [first]
            until = perf_counter() + self.delay
            while len(requests) < self.size:
                try:
                    requests.append(self.queue.get(timeout=max(0, until-perf_counter())))
                except Empty:
                    break
            decisions, histories, replies = zip(*requests)
            try:
                logits, values, state, actions, _ = forward(self.policy, decisions, torch.stack(histories))
                for i, reply in enumerate(replies):
                    length = len(decisions[i].actions)
                    reply.set_result((logits[i, :length], values[i], state[i], actions[i, :length]))
            except Exception as error:
                for reply in replies:
                    if not reply.done():
                        reply.set_exception(error)
