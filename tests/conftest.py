"""Pytest fixtures: Game process wrapper for unit tests."""

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import pytest

DOTNET = os.path.expanduser("~/.dotnet-arm64/dotnet")
if not os.path.isfile(DOTNET):
    DOTNET = shutil.which("dotnet") or DOTNET
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from headless_runtime import headless_command
STARTUP_TIMEOUT = 20
COMMAND_TIMEOUT = 45


class Game:
    """Run the built headless engine with per-process logs and user data."""

    def __init__(self, *, deadline=None):
        self._deadline = deadline
        log_root = ROOT / "logs" / "test-engine"
        log_root.mkdir(parents=True, exist_ok=True)
        self.log_dir = Path(tempfile.mkdtemp(prefix="game-", dir=log_root))
        cwd = self.log_dir / "cwd"
        profile = self.log_dir / "profile"
        roaming = profile / "AppData" / "Roaming"
        local = profile / "AppData" / "Local"
        temp = self.log_dir / "temp"
        for directory in (cwd, roaming, local, temp):
            directory.mkdir(parents=True)

        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith("STEAM")}
        env.update(
            STS2_LIB=str(ROOT / "lib"), STS2_GAME_DIR=str(ROOT / "lib"),
            HOME=str(profile), USERPROFILE=str(profile), APPDATA=str(roaming),
            LOCALAPPDATA=str(local), XDG_DATA_HOME=str(profile / ".local/share"),
            XDG_CONFIG_HOME=str(profile / ".config"), TMP=str(temp), TEMP=str(temp),
            TMPDIR=str(temp),
        )
        self._commands = queue.Queue()
        self._responses = queue.Queue()
        self._last_command = None
        self._last_response = None
        self._closed = False
        # Launch the built DLL directly so terminating this process also stops the engine.
        self.proc = subprocess.Popen(
            headless_command(), cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self._threads = [
            threading.Thread(target=self._drain, args=(self.proc.stdout, "stdout.log"), daemon=True),
            threading.Thread(target=self._drain, args=(self.proc.stderr, "stderr.log"), daemon=True),
            threading.Thread(target=self._write_commands, daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        try:
            ready = self._read(self._remaining(STARTUP_TIMEOUT))
            if ready.get("type") != "ready":
                raise RuntimeError(self._diagnostic(f"Expected ready, got {ready!r}"))
        except BaseException:
            self.close(graceful=False)
            raise

    def _drain(self, stream, filename):
        try:
            with (self.log_dir / filename).open("wb") as log:
                for line in iter(stream.readline, b""):
                    log.write(line)
                    log.flush()
                    if stream is self.proc.stdout and line.lstrip().startswith(b"{"):
                        self._responses.put(line)
        except OSError as error:
            self._responses.put(error)
        finally:
            if stream is self.proc.stdout:
                self._responses.put(None)

    def _write_commands(self):
        try:
            with self.proc.stdin:
                while (command := self._commands.get()) is not None:
                    self.proc.stdin.write(command)
                    self.proc.stdin.flush()
        except OSError as error:
            self._responses.put(error)

    def _diagnostic(self, message):
        detail = (f"{message}; last command={self._last_command!r}; "
                  f"last response={self._last_response!r}; logs={self.log_dir}")
        (self.log_dir / "failure.txt").write_text(detail, encoding="utf-8")
        return detail

    def _remaining(self, timeout):
        if self._deadline is None:
            return timeout
        return max(0, min(timeout, self._deadline - time.monotonic()))

    def _read(self, timeout):
        try:
            line = self._responses.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(self._diagnostic(f"No engine response within {timeout}s")) from None
        if line is None:
            raise RuntimeError(self._diagnostic(f"Engine stdout closed (exit={self.proc.poll()})"))
        if isinstance(line, OSError):
            raise RuntimeError(self._diagnostic(f"Engine pipe error: {line}")) from line
        try:
            self._last_response = json.loads(line)
        except (ValueError, UnicodeError) as error:
            raise RuntimeError(self._diagnostic(f"Invalid engine JSON: {line!r}")) from error
        return self._last_response

    def send(self, cmd):
        self._last_command = cmd
        data = (json.dumps(cmd) + "\n").encode("utf-8")
        with (self.log_dir / "commands.jsonl").open("ab") as log:
            log.write(data)
        started = time.monotonic()
        self._commands.put(data)
        try:
            return self._read(self._remaining(COMMAND_TIMEOUT - (time.monotonic() - started)))
        except BaseException:
            self.close(graceful=False)
            raise

    def start(self, character="Ironclad", seed="test", ascension=0, lang="en"):
        return self.send({"cmd": "start_run", "character": character,
                          "seed": seed, "ascension": ascension, "lang": lang})

    def act(self, action, **args):
        cmd = {"cmd": "action", "action": action}
        if args:
            cmd["args"] = args
        return self.send(cmd)

    def get_map(self):
        return self.send({"cmd": "get_map"})

    def set_player(self, **kwargs):
        cmd = {"cmd": "set_player", **kwargs}
        return self.send(cmd)

    def enter_room(self, room_type, **kwargs):
        cmd = {"cmd": "enter_room", "type": room_type, **kwargs}
        return self.send(cmd)

    def set_draw_order(self, cards):
        return self.send({"cmd": "set_draw_order", "cards": cards})

    def close(self, *, graceful=True):
        if self._closed:
            return
        self._closed = True
        if graceful and self.proc.poll() is None:
            self._commands.put(b'{"cmd":"quit"}\n')
        self._commands.put(None)
        try:
            if not graceful and self.proc.poll() is None:
                self.proc.kill()
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        finally:
            for thread in self._threads:
                thread.join(timeout=5)
            self.proc.stdout.close()
            self.proc.stderr.close()

    # --- Auto-play helpers ---

    def auto_combat(self, state):
        """Play one card or end turn."""
        hand = state.get("hand", [])
        energy = state.get("energy", 0)
        playable = [c for c in hand if c.get("can_play") and c.get("cost", 99) <= energy]
        if playable:
            card = playable[0]
            args = {"card_index": card["index"]}
            if card.get("target_type") == "AnyEnemy":
                enemies = state.get("enemies", [])
                if enemies:
                    args["target_index"] = enemies[0]["index"]
            return self.act("play_card", **args)
        return self.act("end_turn")

    def auto_play_combat(self, state, max_steps=300):
        """Auto-play combat until it ends."""
        for _ in range(max_steps):
            if state.get("decision") != "combat_play":
                return state
            state = self.auto_combat(state)
        raise RuntimeError("Combat did not end")

    def skip_neow(self, state):
        """Skip the Neow event and all follow-up rewards until map_select."""
        for _ in range(20):
            dec = state.get("decision", "")
            if dec == "map_select":
                return state
            if dec == "event_choice":
                opts = [o for o in state["options"] if not o.get("is_locked")]
                state = self.act("choose_option", option_index=opts[0]["index"])
            elif dec == "card_reward":
                state = self.act("skip_card_reward")
            elif dec == "bundle_select":
                state = self.act("select_bundle", bundle_index=0)
            elif dec == "card_select":
                if state.get("min_select", 0) == 0:
                    state = self.act("skip_select")
                else:
                    state = self.act("select_cards", indices="0")
            else:
                state = self.act("proceed")
        return state


@pytest.fixture
def game():
    """Each test gets an independent game process."""
    g = Game()
    try:
        yield g
    finally:
        g.close()
