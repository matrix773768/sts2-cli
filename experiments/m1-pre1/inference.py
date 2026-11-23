"""Model-independent bounded inference groups. Each lane owns its history."""
from concurrent.futures import Future
from queue import Empty, Queue
from threading import Thread
from time import perf_counter

import torch


class InferenceGroup:
    def __init__(self, forward, size, delay):
        self.forward, self.size, self.delay = forward, size, delay
        self.queue = Queue(maxsize=max(2, size*2))
        self.measures = []
        self.thread = Thread(target=self.work, name="pre1-inference")

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.queue.put(None)
        self.thread.join()

    def __call__(self, *inputs):
        reply = Future()
        self.queue.put((inputs, reply))
        return reply.result()

    @torch.inference_mode()
    def work(self):
        while (first := self.queue.get()) is not None:
            requests = [first]
            deadline = perf_counter()+self.delay
            while len(requests) < self.size:
                try:
                    requests.append(self.queue.get(timeout=max(0, deadline-perf_counter())))
                except Empty:
                    break
            data, replies = zip(*requests)
            start = perf_counter()
            try:
                results = list(self.forward(data))
                if len(results) != len(replies):
                    raise ValueError("Inference group returned the wrong batch length")
            except Exception as error:
                for reply in replies:
                    reply.set_exception(error)
            else:
                self.measures.append((len(data), perf_counter()-start))
                for result, reply in zip(results, replies, strict=True):
                    reply.set_result(result)
