"""One-room lookahead from a verified map checkpoint."""
from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
import time
from typing import Callable

from branch_scheduler import BranchResult, BranchTask, run_batch
from room_policy import action, combat_action, reward_action
from search_env import Checkpoint, CheckpointError, _validate_boundary


@dataclass(frozen=True, order=True)
class MapNode:
    row: int
    col: int
    kind: str

    def action(self):
        return action("select_map_node", col=self.col, row=self.row)


def _inventory(items, fields):
    # Canonical value keys retain multiplicities and exported variant attributes.
    return tuple(sorted(json.dumps({k: item[k] for k in fields if k in item},
                                   sort_keys=True, ensure_ascii=False) for item in items or ()))


@dataclass(frozen=True)
class Resources:
    hp: int
    max_hp: int
    gold: int
    act: int
    floor: int
    coord: tuple[int, int] | None
    deck: tuple[str, ...]
    relics: tuple[str, ...]
    potions: tuple[str, ...]

    @classmethod
    def from_state(cls, state, world):
        player = state["player"]
        context = state["context"]
        coord = world.get("current_coord")
        return cls(player["hp"], player["max_hp"], player["gold"],
                   context["act"], context["floor"],
                   (coord["col"], coord["row"]) if coord is not None else None,
                   _inventory(player.get("deck"), ("id", "upgraded", "stats", "enchantment",
                                                   "enchantment_amount", "affliction", "affliction_amount")),
                   _inventory(player.get("relics"), ("name", "vars")),
                   _inventory(player.get("potions"), ("name", "vars")))


def _changes(before, after):
    before, after = Counter(before), Counter(after)
    return {"added": [json.loads(item) for item in sorted((after - before).elements())],
            "removed": [json.loads(item) for item in sorted((before - after).elements())]}


def resource_changes(before, after):
    return {"hp": after.hp - before.hp, "max_hp": after.max_hp - before.max_hp,
            "gold": after.gold - before.gold,
            "deck": _changes(before.deck, after.deck),
            "relics": _changes(before.relics, after.relics),
            "potions": _changes(before.potions, after.potions)}


@dataclass(frozen=True)
class Score:
    outcome_rank: int
    components: dict[str, float]

    @property
    def total(self):
        return sum(self.components.values())


@dataclass(frozen=True)
class Heuristic:
    hp_weight: float = 1.0
    gold_weight: float = 0.05

    def __post_init__(self):
        if not all(math.isfinite(w) and w >= 0 for w in (self.hp_weight, self.gold_weight)):
            raise ValueError("Heuristic weights must be finite and nonnegative")

    def __call__(self, before, after, outcome):
        rank = {"death": 0, "map": 1, "victory": 2}[outcome]
        return Score(rank, {"hp": self.hp_weight * (after.hp - before.hp),
                            "gold": self.gold_weight * (after.gold - before.gold)})


Policy = Callable[[dict], dict | None]


def _unsupported(_):
    return None


@dataclass(frozen=True)
class SearchConfig:
    checkpoint_dir: Path = Path("saves")
    log_root: Path | None = None
    max_branches: int = 16
    max_workers: int = 4
    max_actions: int = 300
    branch_timeout: float = 30
    search_timeout: float = 60
    combat: Policy = combat_action
    reward: Policy = reward_action
    other: Policy = _unsupported
    evaluator: Callable[[Resources, Resources, str], Score] = field(default_factory=Heuristic)

    def __post_init__(self):
        if min(self.max_branches, self.max_workers) < 1 or self.max_actions < 0:
            raise ValueError("Invalid branch, worker or action limit")
        if not all(math.isfinite(t) and t > 0 for t in (self.branch_timeout, self.search_timeout)):
            raise ValueError("Time limits must be finite and positive")


@dataclass(frozen=True)
class Candidate:
    node: MapNode
    branch: BranchResult
    resources: Resources | None = None
    changes: dict | None = None
    outcome: str | None = None
    score: Score | None = None
    reason: str | None = None


@dataclass(frozen=True)
class SearchDecision:
    recommended_action: dict | None
    candidates: tuple[Candidate, ...]
    initial: Resources
    elapsed: float
    reason: str | None = None


def _root(checkpoint):
    for data, digest in ((checkpoint.observation, checkpoint.observation_sha256),
                         (checkpoint.world_map, checkpoint.map_sha256)):
        if sha256(data).hexdigest() != digest:
            raise CheckpointError("Checkpoint observation or map digest mismatch")
    state, world = json.loads(checkpoint.observation), json.loads(checkpoint.world_map)
    _validate_boundary(state, world)
    nodes = tuple(sorted(MapNode(n["row"], n["col"], n["type"]) for n in state["choices"]))
    return Resources.from_state(state, world), nodes


def _branch_policy(node, config):
    sent_entry = False

    def policy(state):
        nonlocal sent_entry
        decision = state["decision"]
        if not sent_entry:
            sent_entry = True
            return node.action() if decision == "map_select" else None
        room_policy = {"combat_play": config.combat, "card_reward": config.reward}.get(
            decision, config.other
        )
        next_action = room_policy(state)
        if next_action is not None and next_action.get("action") == "select_map_node":
            return None
        return next_action

    return policy


def _candidate(node, result, initial, evaluator):
    observed = result.observation or {}
    prefix = result.position.prefix if result.position else ()
    resources = changes = None
    if prefix and "player" in observed:
        resources = Resources.from_state(observed, json.loads(prefix[-1].world_map))
        changes = resource_changes(initial, resources)
    if not result.successful:
        decision = observed.get("decision")
        reason = result.error or (f"Unsupported decision: {decision}" if result.status == "unsupported"
                                  else result.status)
        return Candidate(node, result, resources, changes, reason=reason)
    if resources is None or json.loads(prefix[0].world_map).get("current_coord") != {"col": node.col, "row": node.row}:
        return Candidate(node, result, resources, changes, reason="Requested map entry was not verified")
    if result.status == "terminal":
        outcome = "victory" if result.victory else "death"
    elif (observed.get("decision") == "map_select" and observed["context"].get("room_type") == "Map"
          and (resources.act, resources.floor) > (initial.act, initial.floor)):
        outcome = "map"
    else:
        return Candidate(node, result, resources, changes, reason="No comparable room boundary")
    score = evaluator(initial, resources, outcome)
    if not math.isfinite(score.total):
        raise ValueError("Evaluator returned a non-finite score")
    return Candidate(node, result, resources, changes, outcome, score)


def search_map(checkpoint: Checkpoint, config: SearchConfig = SearchConfig()) -> SearchDecision:
    """Recommend a current legal map edge without mutating the root or any caller environment.

    All legal edges must yield comparable results. Ties take the lowest (row, col).
    Callback time limits are cooperative, as in the underlying scheduler.
    """
    started = time.monotonic()
    initial, nodes = _root(checkpoint)
    tasks = [BranchTask(checkpoint, policy=_branch_policy(node, config), stop_at=("map_select",),
                        max_actions=config.max_actions, timeout=config.branch_timeout,
                        task_id=f"{node.col},{node.row}")
             for node in nodes[:config.max_branches]]
    remaining = config.search_timeout - (time.monotonic() - started)
    if remaining > 0:
        results = run_batch(tasks, game_build=checkpoint.build.game_build,
                            checkpoint_dir=config.checkpoint_dir, log_root=config.log_root,
                            max_workers=config.max_workers, timeout=remaining)
    else:
        results = [BranchResult(task.task_id, "batch_deadline") for task in tasks]
    results.extend(BranchResult(f"{node.col},{node.row}", "branch_budget")
                   for node in nodes[len(tasks):])
    candidates = tuple(_candidate(node, result, initial, config.evaluator)
                       for node, result in zip(nodes, results))
    eligible = [candidate for candidate in candidates if candidate.score is not None]
    winner = (max(eligible, key=lambda c: (c.score.outcome_rank, c.score.total))
              if eligible and len(eligible) == len(candidates) else None)
    return SearchDecision(winner.node.action() if winner else None, candidates, initial,
                          time.monotonic() - started,
                          None if winner else f"Insufficient comparable results ({len(eligible)}/{len(nodes)})")
