"""Bounded scheduling for independent search environments."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
import math
import threading
import time
from typing import Callable, Sequence

from engine_client import EngineCancelled
from search_env import Checkpoint, CheckpointError, SearchEnv, SearchPosition


@dataclass(frozen=True)
class BranchTask:
    root: Checkpoint | SearchPosition
    actions: tuple[dict, ...] | None = None
    policy: Callable[[dict], dict | None] | None = None
    stop_at: tuple[str, ...] = ("card_reward", "map_select")
    max_actions: int = 300
    timeout: float = 60
    task_id: str | None = None

    def __post_init__(self):
        if (self.actions is None) == (self.policy is None):
            raise ValueError("Supply either actions or policy")
        if self.max_actions < 0 or not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("Invalid action or time budget")


@dataclass
class BranchResult:
    task_id: str | None
    status: str
    attempted: bool = False
    actions: int = 0
    observation: dict | None = None
    position: SearchPosition | None = None
    victory: bool | None = None
    error: str | None = None
    pid: int | None = None
    log_dir: str | None = None
    returncode: int | None = None
    elapsed: float = 0
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def successful(self):
        return self.status in ("boundary", "terminal")


def _execute(task, config, batch_deadline, cancelled, on_process):
    started = time.monotonic()
    deadline = min(started + task.timeout, batch_deadline)
    result = BranchResult(task.task_id, "canceled")
    process = None
    env = None
    execution_started = None

    def spawned(child, log_dir):
        nonlocal process
        process = child
        result.pid, result.log_dir = child.pid, str(log_dir)
        if on_process is not None:
            on_process(child, log_dir)

    try:
        if cancelled():
            return result
        if started >= batch_deadline:
            result.status = "batch_deadline"
            return result
        result.attempted = True
        env = SearchEnv(**config, deadline=deadline, cancelled=cancelled,
                        on_process=spawned, timings=result.timings)
        if isinstance(task.root, SearchPosition):
            state = env.restore_position(task.root)
        else:
            state = env.reset(checkpoint=task.root)
        execution_started = time.monotonic()
        while True:
            result.observation = state
            decision = state["decision"]
            if cancelled():
                result.status = "canceled"
                break
            if time.monotonic() >= deadline:
                result.status = "batch_deadline" if deadline == batch_deadline else "timeout"
                break
            if decision == "game_over":
                if type(state.get("victory")) is not bool:
                    raise ValueError("Terminal response missing boolean victory")
                result.status, result.victory = "terminal", state["victory"]
                break
            # A map root is a starting point, not the next map boundary.
            if decision in task.stop_at and (result.actions or decision != "map_select"):
                result.status = "boundary"
                break
            if result.actions >= task.max_actions:
                result.status = "action_budget"
                break
            if task.policy is not None:
                try:
                    action = task.policy(state)
                except Exception as error:
                    result.status, result.error = "policy_error", str(error)
                    break
            else:
                action = task.actions[result.actions] if result.actions < len(task.actions) else None
            if action is None:
                result.status = "unsupported"
                break
            state = env.step(action)
            result.actions += 1
        result.position = env.position()
    except EngineCancelled as error:
        result.status, result.error = "canceled", str(error)
    except TimeoutError as error:
        result.status = "batch_deadline" if time.monotonic() >= batch_deadline else "timeout"
        result.error = str(error)
    except CheckpointError as error:
        result.status, result.error = "checkpoint_error", str(error)
    except Exception as error:
        result.status, result.error = "engine_error", str(error)
    finally:
        if execution_started is not None:
            result.timings["execution"] = time.monotonic() - execution_started
        try:
            if env is not None:
                env.close()
        except Exception as error:
            result.status, result.error = "engine_error", f"Cleanup failed: {error}"
        if process is not None:
            result.returncode = process.poll()
            if result.returncode is None or (result.successful and result.returncode != 0):
                result.status, result.error = "engine_error", f"Engine exit status: {result.returncode}"
        if not result.successful:
            result.victory = None
        result.elapsed = time.monotonic() - started
    return result


def run_batch(tasks: Sequence[BranchTask], *, game_build, checkpoint_dir, log_root=None,
              max_workers=1, timeout=None, cancel_event=None, on_process=None):
    """Return results in input order. Cancellation interrupts IPC and is cooperative in policy callbacks.

    Task time includes restore/replay, but the action budget counts only subsequent actions.
    A batch deadline stops submissions and bounds in-flight IPC; cleanup may outlast the deadline.
    """
    if max_workers < 1 or (timeout is not None and (not math.isfinite(timeout) or timeout <= 0)):
        raise ValueError("Invalid batch concurrency or deadline")
    deadline = math.inf if timeout is None else time.monotonic() + timeout
    local_cancel = threading.Event()

    def cancelled():
        return local_cancel.is_set() or (cancel_event is not None and cancel_event.is_set())

    config = dict(game_build=game_build, checkpoint_dir=checkpoint_dir, log_root=log_root)
    source = iter(tasks)
    results = []
    active = {}
    exhausted = False
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        try:
            while active or not exhausted:
                while not exhausted and len(active) < max_workers:
                    task = next(source, None)
                    if task is None:
                        exhausted = True
                        break
                    index = len(results)
                    if cancelled() or time.monotonic() >= deadline:
                        status = "canceled" if cancelled() else "batch_deadline"
                        results.append(BranchResult(task.task_id, status))
                        continue
                    results.append(None)
                    future = pool.submit(_execute, task, config, deadline, cancelled, on_process)
                    active[future] = index
                if active:
                    done, _ = wait(active, return_when=FIRST_COMPLETED)
                    for future in done:
                        results[active.pop(future)] = future.result()
        finally:
            local_cancel.set()
    return results
