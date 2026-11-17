"""Isolated, synchronous transport for the headless engine."""

import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time

from headless_runtime import headless_command

ROOT = Path(__file__).resolve().parents[1]


class EngineClient:
    """Run the built headless engine with per-process logs and user data."""

    def __init__(self, *, deadline=None, log_root=None, startup_timeout=20, command_timeout=45):
        self._deadline = deadline
        self._lock = threading.RLock()
        self._command_timeout = command_timeout
        self._runtime_ready = threading.Event()
        self.runtime_version = None
        log_root = Path(log_root or ROOT / "logs" / "search-engine").resolve()
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
        threads = [
            threading.Thread(target=self._drain, args=(self.proc.stdout, "stdout.log"), daemon=True),
            threading.Thread(target=self._drain, args=(self.proc.stderr, "stderr.log"), daemon=True),
            threading.Thread(target=self._write_commands, daemon=True),
        ]
        self._threads = []
        try:
            for thread in threads:
                thread.start()
                self._threads.append(thread)
            startup_end = time.monotonic() + startup_timeout
            self.ready = ready = self._read(self._remaining(startup_timeout))
            if ready.get("type") != "ready":
                raise RuntimeError(self._diagnostic(f"Expected ready, got {ready!r}"))
            self._runtime_ready.wait(self._remaining(max(0, startup_end - time.monotonic())))
            if not self.runtime_version or not self.runtime_version.startswith("9."):
                raise RuntimeError(self._diagnostic("Missing CoreCLR 9 runtime announcement"))
        except BaseException:
            self.close(graceful=False)
            raise

    def _drain(self, stream, filename):
        try:
            with (self.log_dir / filename).open("wb") as log:
                for line in iter(stream.readline, b""):
                    log.write(line)
                    log.flush()
                    if stream is self.proc.stderr and line.startswith(b"[INFO] CoreCLR "):
                        self.runtime_version = line.split()[-1].decode("ascii")
                        self._runtime_ready.set()
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
        try:
            (self.log_dir / "failure.txt").write_text(detail, encoding="utf-8")
        except OSError:
            pass  # Reporting must preserve the original engine failure.
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
        if not isinstance(self._last_response, dict) or "type" not in self._last_response:
            raise RuntimeError(self._diagnostic("Expected a typed engine response"))
        return self._last_response

    def send(self, cmd):
        with self._lock:
            return self._send(cmd)

    def _send(self, cmd):
        if self._closed:
            raise RuntimeError("Engine client is closed")
        if self._remaining(self._command_timeout) <= 0:
            self.close(graceful=False)
            raise TimeoutError(self._diagnostic("Engine run deadline exceeded"))
        self._last_command = cmd
        data = (json.dumps(cmd) + "\n").encode("utf-8")
        with (self.log_dir / "commands.jsonl").open("ab") as log:
            log.write(data)
        started = time.monotonic()
        self._commands.put(data)
        try:
            return self._read(self._remaining(self._command_timeout - (time.monotonic() - started)))
        except BaseException:
            self.close(graceful=False)
            raise

    def close(self, *, graceful=True):
        with self._lock:
            self._close(graceful)

    def _close(self, graceful):
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
            self.proc.stdin.close()
            self.proc.stdout.close()
            self.proc.stderr.close()
