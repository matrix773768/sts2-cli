"""Deterministic, process-isolated search from native map checkpoints."""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import time
from uuid import uuid4

from engine_client import EngineClient, ROOT
from headless_runtime import ENGINE

ADAPTER_VERSION = 1


class EngineFailure(RuntimeError):
    """The current engine session can no longer be used."""


class CheckpointError(ValueError):
    """The checkpoint cannot be created or restored."""


class ReplayMismatch(CheckpointError):
    """Replay diverged from its recorded response or map."""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(data):
    return sha256(data).hexdigest()


def _compare(expected, actual, label, path="$"):
    if type(expected) is type(actual):
        if isinstance(expected, dict):
            for key in expected:
                if key not in actual:
                    raise ReplayMismatch(f"{label}: missing field at {path}.{key}")
                _compare(expected[key], actual[key], label, f"{path}.{key}")
            for key in actual.keys() - expected.keys():
                raise ReplayMismatch(f"{label}: unexpected field at {path}.{key}")
            return
        if isinstance(expected, list):
            for index, (left, right) in enumerate(zip(expected, actual)):
                _compare(left, right, label, f"{path}[{index}]")
            if len(expected) != len(actual):
                raise ReplayMismatch(
                    f"{label}: first difference at {path}[{min(len(expected), len(actual))}]: "
                    f"array lengths {len(expected)} != {len(actual)}"
                )
            return
        if not isinstance(expected, (dict, list)) and expected == actual:
            return
    raise ReplayMismatch(f"{label}: first difference at {path}: {expected!r} != {actual!r}")


@dataclass(frozen=True)
class Build:
    game_build: str
    native_sha256: str
    engine_sha256: str
    adapter_version: int


@dataclass(frozen=True)
class Checkpoint:
    path: Path
    sha256: str
    build: Build
    runtime_version: str
    protocol_version: str
    lang: str
    observation: bytes
    world_map: bytes
    observation_sha256: str
    map_sha256: str
    source: tuple[str, ...]


@dataclass(frozen=True)
class ReplayStep:
    action: bytes
    observation: bytes
    world_map: bytes


@dataclass(frozen=True)
class SearchPosition:
    checkpoint: Checkpoint
    prefix: tuple[ReplayStep, ...]


def _coord(node):
    col, row = node["col"], node["row"]
    if type(col) is not int or type(row) is not int:
        raise ValueError("Map coordinates must be integers")
    return col, row


def _validate_boundary(state, world):
    """Check that choices match native outgoing edges, including special starts."""
    try:
        context = state["context"]
        if (state["decision"] != "map_select" or context["room_type"] != "Map"
                or context != world["context"]):
            raise ValueError("Map context does not match the current decision")
        if state["act"] != context["act"] or state["floor"] != context["floor"]:
            raise ValueError("Inconsistent map act or floor")
        rows = [node for row in world["rows"] for node in row]
        nodes = {_coord(node): node for node in rows}
        if len(nodes) != len(rows):
            raise ValueError("Duplicate map coordinates")
        boss = world["boss"]
        nodes.setdefault(_coord(boss), boss)
        start = world["starting_point"]
        nodes[_coord(start)] = start
        current = world.get("current_coord")
        if current is None:
            if state["floor"] != 0 or state["act"] <= 1 or start["type"] != "Ancient":
                raise ValueError("Unsupported unvisited map boundary")
            expected = [start]
        else:
            node = nodes[_coord(current)]
            if node is not start and not (node.get("visited") is True and node.get("current") is True):
                raise ValueError("Current coordinate is not an active visited node")
            if node is start and state["floor"] != 1:
                raise ValueError("Visited start requires floor 1")
            expected = node.get("children") or []
        choices = state["choices"]
        offered = {_coord(choice): choice["type"] for choice in choices}
        edges = {_coord(edge): nodes[_coord(edge)]["type"] for edge in expected}
        if not edges or len(expected) != len(edges) or len(choices) != len(offered) or offered != edges:
            raise ValueError("Decision choices differ from native map edges")
    except (KeyError, TypeError, ValueError) as error:
        raise CheckpointError(f"Unsupported map checkpoint boundary: {error}") from error


class SearchEnv:
    """Single-owner environment. Create separate instances for concurrent runs."""

    def __init__(self, *, game_build, checkpoint_dir, log_root=None,
                 startup_timeout=20, command_timeout=45, run_timeout=300,
                 deadline=None, cancelled=None, on_process=None, timings=None):
        self._config = dict(game_build=game_build, checkpoint_dir=Path(checkpoint_dir).resolve(),
                            log_root=log_root, startup_timeout=startup_timeout,
                            command_timeout=command_timeout, run_timeout=run_timeout)
        self._deadline = deadline
        self._cancelled = cancelled
        self._on_process = on_process
        self._timings = timings
        self._engine = None
        self._build_id = None
        self._state = None
        self._root = None
        self._prefix = []
        self._source = ()
        self._lang = "en"

    def _timed(self, label, fn, *args, **kwargs):
        if self._timings is None:
            return fn(*args, **kwargs)
        start = time.monotonic()
        try:
            return fn(*args, **kwargs)
        finally:
            self._timings[label] = self._timings.get(label, 0) + time.monotonic() - start

    def _build(self):
        try:
            return Build(self._config["game_build"], _digest((ROOT / "lib/sts2.dll").read_bytes()),
                         _digest(ENGINE.read_bytes()), ADAPTER_VERSION)
        except OSError as error:
            raise CheckpointError(f"Cannot fingerprint local engine: {error}") from error

    def _request(self, command, expected, *, timing=None):
        if self._engine is None:
            raise EngineFailure("No active engine session")
        try:
            response = self._timed(timing or command["cmd"], self._engine.send, command)
            decision = response.get("decision")
            if (response.get("type") != expected or
                    expected == "decision" and (
                        not isinstance(decision, str) or not decision
                        or decision in ("combat_turn_timeout", "unknown")
                    )):
                raise EngineFailure(self._engine._diagnostic(
                    f"Unexpected engine response for {command['cmd']}"
                ))
            return response
        except BaseException:
            self._close(graceful=False)
            raise

    def _payload(self, checkpoint, build):
        if checkpoint.build != build:
            raise CheckpointError("Checkpoint build or adapter mismatch")
        try:
            payload = checkpoint.path.read_bytes()
        except OSError as error:
            raise CheckpointError(f"Cannot read checkpoint: {error}") from error
        for data, expected in ((payload, checkpoint.sha256),
                               (checkpoint.observation, checkpoint.observation_sha256),
                               (checkpoint.world_map, checkpoint.map_sha256)):
            if _digest(data) != expected:
                raise CheckpointError("Checkpoint SHA-256 mismatch")
        return payload

    def reset(self, *, seed=None, checkpoint=None, character="Ironclad", ascension=0, lang="en"):
        """Open a fresh process from an explicit seed or a verified checkpoint."""
        if (seed is None) == (checkpoint is None):
            raise ValueError("Specify exactly one of seed and checkpoint")
        self.close()
        self._build_id = self._timed('fingerprint', self._build)
        payload = self._timed('checkpoint_validation', self._payload, checkpoint, self._build_id) if checkpoint else None
        self._root = checkpoint
        self._prefix.clear()
        self._lang = checkpoint.lang if checkpoint else lang
        self._source = (("checkpoint", checkpoint.sha256) if checkpoint else
                        ("seed", seed, character, str(ascension)))
        config = self._config
        try:
            deadline = time.monotonic() + config["run_timeout"]
            if self._deadline is not None:
                deadline = min(deadline, self._deadline)
            self._engine = self._timed('startup', EngineClient,
                deadline=deadline, cancelled=self._cancelled, on_process=self._on_process,
                log_root=config["log_root"], startup_timeout=config["startup_timeout"],
                command_timeout=config["command_timeout"],
            )
            if checkpoint:
                if (checkpoint.runtime_version != self._engine.runtime_version or
                        checkpoint.protocol_version != self._engine.ready.get("version")):
                    raise CheckpointError("Checkpoint runtime or protocol version mismatch")
                command = dict(cmd="load_save", json=payload.decode("utf-8-sig"), lang=self._lang)
            else:
                command = dict(cmd="start_run", seed=seed, character=character,
                               ascension=ascension, lang=lang)
            self._state = self._request(command, "decision")
            if checkpoint:
                self._timed("checkpoint_validation", _compare, json.loads(checkpoint.observation),
                            self._state, "load decision")
                world = self._request({"cmd": "get_map", "include_start": True}, "map",
                                      timing="restore_map")
                self._timed("checkpoint_validation", self._verify_restore, checkpoint, payload, world)
            return self.observe()
        except BaseException:
            self.close()
            raise

    def _verify_restore(self, checkpoint, payload, world):
        _compare(json.loads(checkpoint.world_map), world, "load map")
        _validate_boundary(self._state, world)
        if self._payload(checkpoint, self._build_id) != payload:
            raise CheckpointError("Checkpoint changed during restore")

    def observe(self):
        """Return a detached copy of the cached decision without engine I/O."""
        if self._state is None:
            raise EngineFailure("No active decision")
        return json.loads(_json(self._state))

    def step(self, action):
        """Execute an action dictionary with 'action' and optional 'args'."""
        command = self._advance(action)
        if self._root is not None:
            self._timed('trace', self._record_step, command, self.get_map())
        return self.observe()

    def _record_step(self, command, world):
        self._prefix.append(ReplayStep(command, _json(self._state), _json(world)))

    def _advance(self, action):
        if self._state is None or self._state.get("decision") == "game_over":
            raise EngineFailure("No active nonterminal decision")
        if (action.keys() - {"cmd", "action", "args"} or
                action.get("cmd", "action") != "action" or not isinstance(action.get("action"), str)
                or not isinstance(action.get("args", {}), dict)):
            raise ValueError("Expected an action name and optional argument dictionary")
        command = {**action, "cmd": "action"}
        encoded = _json(command)
        self._state = self._request(command, "decision")
        return encoded

    def get_map(self):
        return self._request({"cmd": "get_map", "include_start": True}, "map")

    def save_checkpoint(self):
        """Publish a local immutable checkpoint only after independent validation."""
        state = self.observe()
        if state.get("decision") != "map_select" or state.get("context", {}).get("room_type") != "Map":
            raise CheckpointError("Checkpoint requires a map_select decision in Map")
        world = self.get_map()
        _validate_boundary(state, world)
        if self._build() != self._build_id:
            raise CheckpointError("Engine files changed during the session")
        observation, world_map = _json(state), _json(world)
        directory = self._config["checkpoint_dir"]
        directory.mkdir(parents=True, exist_ok=True)
        candidate = directory / f"map-{uuid4().hex}.save"
        try:
            result = self._request({"cmd": "write_continue_save", "path": str(candidate)}, "save_result")
            if (result.get("success") is not True or result.get("room_type") != "MapRoom"
                    or result.get("path") != str(candidate) or not candidate.is_file()):
                raise CheckpointError(f"Unexpected checkpoint save result: {result!r}")
            payload = candidate.read_bytes()
            try:
                document = payload.decode("utf-8-sig")
                native_save = json.loads(document)
            except (ValueError, UnicodeError) as error:
                raise CheckpointError("Invalid native checkpoint JSON") from error
            # The protocol reports .NET string length, in UTF-16 code units.
            if (not isinstance(native_save, dict)
                    or result.get("size") != len(document.encode("utf-16-le")) // 2):
                raise CheckpointError("Invalid native checkpoint data or reported size")
            checkpoint = Checkpoint(
                candidate, _digest(payload), self._build_id, self._engine.runtime_version,
                self._engine.ready["version"], self._lang, observation, world_map,
                _digest(observation), _digest(world_map), self._source,
            )
            with self.branch(checkpoint):
                pass
            if self._payload(checkpoint, self._build_id) != payload:
                raise CheckpointError("Checkpoint changed during validation")
        except BaseException:
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass  # Preserve the original failure if cleanup is denied.
            raise
        self._root = checkpoint
        self._prefix.clear()
        self._source = ("checkpoint", checkpoint.sha256)
        return checkpoint

    def branch(self, checkpoint):
        """Return a fresh environment at a verified checkpoint."""
        child = SearchEnv(**self._config)
        child.reset(checkpoint=checkpoint)
        return child

    def position(self):
        """Capture a replayable position relative to the most recent checkpoint."""
        if self._root is None or self._state is None:
            raise CheckpointError("An active checkpoint-based session is required")
        return SearchPosition(self._root, tuple(self._prefix))

    def replay(self, position):
        """Open a fresh branch and stop at the first replay mismatch."""
        child = SearchEnv(**self._config)
        child.restore_position(position)
        return child

    def restore_position(self, position):
        """Reset this environment and verify a recorded prefix in a fresh process."""
        self.reset(checkpoint=position.checkpoint)
        try:
            for index, expected in enumerate(position.prefix, 1):
                command = self._advance(json.loads(expected.action))
                _compare(json.loads(expected.observation), self._state, f"step {index} decision")
                world = self.get_map()
                _compare(json.loads(expected.world_map), world, f"step {index} map")
                self._timed("trace", self._record_step, command, world)
            return self.observe()
        except BaseException:
            self.close()
            raise

    def close(self):
        self._close(graceful=True)

    def _close(self, *, graceful):
        engine, self._engine = self._engine, None
        self._state = None
        if engine:
            self._timed('shutdown', engine.close, graceful=graceful)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
