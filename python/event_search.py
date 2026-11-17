"""Look ahead from a replayable native event decision."""
from dataclasses import dataclass
import json
import time

from branch_scheduler import BranchResult, BranchTask, run_batch
from map_search import Resources, Score, SearchConfig, evaluate_outcome, resource_changes
from room_policy import action
from search_env import SearchPosition


@dataclass(frozen=True)
class EventOption:
    index: int
    title: str
    text_key: str

    def action(self):
        return action("choose_option", option_index=self.index)


@dataclass(frozen=True)
class EventCandidate:
    option: EventOption
    branch: BranchResult
    resources: Resources | None = None
    changes: dict | None = None
    outcome: str | None = None
    score: Score | None = None
    reason: str | None = None


@dataclass(frozen=True)
class EventDecision:
    event_name: str
    recommended_action: dict | None
    candidates: tuple[EventCandidate, ...]
    initial: Resources
    elapsed: float
    reason: str | None = None


def _indices(items):
    indices = [item.get("index") for item in items]
    if any(type(i) is not int or i < 0 for i in indices) or len(set(indices)) != len(indices):
        raise ValueError("Invalid native choice indices")
    return sorted(indices)


def _options(state):
    offered = [o for o in state["options"] if o.get("is_locked") is False]
    _indices(offered)
    return tuple(sorted((EventOption(o["index"], o["title"], o["text_key"]) for o in offered),
                        key=lambda option: option.index))


def _selection_action(state):
    decision = state["decision"]
    if decision == "card_select":
        low, high = state["min_select"], state["max_select"]
        indices = _indices(state["cards"])
        if type(low) is not int or type(high) is not int or not 0 <= low <= min(high, len(indices)):
            return None
        if low == 0:
            return action("skip_select")
        return action("select_cards", indices=",".join(map(str, indices[:low])))
    if decision == "card_reward" and state.get("from_event") is True:
        indices = _indices(state["cards"])
        if indices:
            return action("select_card_reward", card_index=indices[0])
        if state.get("can_skip") is True:
            return action("skip_card_reward")
    if decision == "bundle_select":
        indices = _indices(state["bundles"])
        if indices:
            return action("select_bundle", bundle_index=indices[0])
    return None


class _EventPolicy:
    def __init__(self, option, event_name, initial):
        self.option = option
        self.event_name = event_name
        self.initial = initial
        self.seen = set()
        self.reason = None

    def __call__(self, state):
        context = state["context"]
        if (context.get("room_type"), context.get("act"), context.get("floor")) != (
            "Event", self.initial.act, self.initial.floor
        ):
            self.reason = "Decision outside the original event room"
            return None
        if state["decision"] == "event_choice":
            if state["event_name"] != self.event_name:
                self.reason = "Unexpected event"
                return None
            key = json.dumps(state, sort_keys=True)
            if key in self.seen:
                self.reason = "Repeated event decision"
                return None
            options = _options(state)
            choice = (options[0] if options else None) if self.seen else self.option
            self.seen.add(key)
            if choice in options:
                return choice.action()
        else:
            selected = _selection_action(state)
            if selected is not None:
                return selected
        self.reason = f"Unsupported decision: {state['decision']}"
        return None


def _candidate(option, result, position, initial, policy, evaluator):
    prefix = result.position.prefix if result.position else ()
    observed = result.observation or {}
    resources = (Resources.from_state(observed, json.loads(prefix[-1].world_map))
                 if prefix and "player" in observed else None)
    changes = resource_changes(initial, resources) if resources else None
    if not result.successful:
        reason = result.error or policy.reason or result.status
        return EventCandidate(option, result, resources, changes, reason=reason)

    offset = len(position.prefix)
    expected = option.action()
    expected["cmd"] = "action"
    if resources is None or len(prefix) <= offset or json.loads(prefix[offset].action) != expected:
        return EventCandidate(option, result, resources, changes, reason="Event choice was not verified")
    if result.status == "terminal":
        outcome = "victory" if result.victory else "death"
    elif (observed.get("decision") == "map_select" and observed["context"].get("room_type") == "Map"
          and (resources.act, resources.floor, resources.coord) == (initial.act, initial.floor, initial.coord)):
        outcome = "map"
    else:
        return EventCandidate(option, result, resources, changes, reason="No comparable event boundary")
    score = evaluate_outcome(initial, resources, outcome, evaluator)
    return EventCandidate(option, result, resources, changes, outcome, score)


def search_event(position: SearchPosition, config: SearchConfig = SearchConfig()) -> EventDecision:
    """Evaluate each unlocked option from a verified replay, without advancing the caller.

    Uses SearchConfig's evaluator and budgets. Event continuations use the fixed event
    policy. Every unlocked option needs a comparable result to issue a recommendation.
    Ties take the lowest offered index.
    """
    started = time.monotonic()
    if not position.prefix:
        raise ValueError("An event SearchPosition needs a recorded action prefix")
    target = position.prefix[-1]
    state, world = json.loads(target.observation), json.loads(target.world_map)
    if state.get("decision") != "event_choice" or state["context"].get("room_type") != "Event":
        raise ValueError("SearchPosition must end at an event_choice")
    initial = Resources.from_state(state, world)
    event_name = state["event_name"]
    options = _options(state)
    policies = [_EventPolicy(option, event_name, initial) for option in options]
    tasks = [BranchTask(position, policy=policy, stop_at=("map_select",), max_actions=config.max_actions,
                        timeout=config.branch_timeout, task_id=str(policy.option.index))
             for policy in policies[:config.max_branches]]
    remaining = config.search_timeout - (time.monotonic() - started)
    if tasks and remaining > 0:
        results = run_batch(tasks, game_build=position.checkpoint.build.game_build,
                            checkpoint_dir=config.checkpoint_dir, log_root=config.log_root,
                            max_workers=config.max_workers, timeout=remaining)
    else:
        results = [BranchResult(task.task_id, "batch_deadline") for task in tasks]
    results.extend(BranchResult(str(option.index), "branch_budget") for option in options[len(tasks):])
    candidates = tuple(_candidate(option, result, position, initial, policy, config.evaluator)
                       for option, result, policy in zip(options, results, policies))
    eligible = [candidate for candidate in candidates if candidate.score is not None]
    winner = (max(eligible, key=lambda c: (c.score.outcome_rank, c.score.total))
              if eligible and len(eligible) == len(candidates) else None)
    return EventDecision(event_name, winner.option.action() if winner else None, candidates, initial,
                         time.monotonic() - started,
                         None if winner else f"Insufficient comparable results ({len(eligible)}/{len(options)})")
