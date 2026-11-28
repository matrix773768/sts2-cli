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


class EngineCancelled(RuntimeError):
    """External cancellation interrupted engine I/O."""

class EngineClient:
    """Run the built headless engine with per-process logs and user data."""

    def __init__(self, *, deadline=None, log_root=None, startup_timeout=20, command_timeout=45,
                 cancelled=None, on_process=None, command=None, extra_env=None):
        self._deadline = deadline
        self._cancelled = cancelled
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
        if extra_env:
            env.update(extra_env)
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
        self._phase = "launch"
        self._launched_at = time.monotonic()
        startup_end = self._launched_at + startup_timeout
        # Launch the built DLL directly so terminating this process also stops the engine.
        self._check_cancelled()
        if self._remaining(startup_timeout) <= 0:
            raise TimeoutError("Engine launch deadline exceeded")
        self.proc = subprocess.Popen(
            headless_command() if command is None else command, cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        threads = [
            threading.Thread(target=self._drain, args=(self.proc.stdout, "stdout.log"), daemon=True),
            threading.Thread(target=self._drain, args=(self.proc.stderr, "stderr.log"), daemon=True),
            threading.Thread(target=self._write_commands, daemon=True),
        ]
        self._threads = []
        try:
            if on_process is not None:
                on_process(self.proc, self.log_dir)
            for thread in threads:
                thread.start()
                self._threads.append(thread)
            self._phase = "ready"
            self.ready = ready = self._read(self._remaining(max(0, startup_end - time.monotonic())))
            if ready.get("type") != "ready":
                raise RuntimeError(self._diagnostic(f"Expected ready, got {ready!r}"))
            self._phase = "runtime_attestation"
            self._runtime_ready.wait(self._remaining(max(0, startup_end - time.monotonic())))
            expected_runtime = env.get("STS2_DOTNET_VERSION")
            if not self.runtime_version or not self.runtime_version.startswith("9.") or (
                    expected_runtime and self.runtime_version != expected_runtime):
                raise RuntimeError(self._diagnostic(f"Unexpected CoreCLR runtime: {self.runtime_version!r}"))
            self._phase = "idle"
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
            elif stream is self.proc.stderr:
                self._runtime_ready.set()

    def _write_commands(self):
        try:
            with self.proc.stdin:
                while (command := self._commands.get()) is not None:
                    self.proc.stdin.write(command)
                    self.proc.stdin.flush()
        except OSError as error:
            self._responses.put(error)

    def _diagnostic(self, message):
        detail = (f"{message}; phase={self._phase}; pid={self.proc.pid}; exit={self.proc.poll()}; "
                  f"last command={self._last_command!r}; "
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
        end = time.monotonic() + timeout
        while True:
            self._check_cancelled()
            remaining = max(0, end - time.monotonic())
            try:
                line = self._responses.get(timeout=min(remaining, 0.05) if self._cancelled else remaining)
                break
            except queue.Empty:
                if time.monotonic() >= end:
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

    def _check_cancelled(self):
        if self._cancelled is not None and self._cancelled():
            raise EngineCancelled("Engine request canceled")

    def send(self, cmd):
        with self._lock:
            return self._send(cmd)

    def _send(self, cmd):
        if self._closed:
            raise RuntimeError("Engine client is closed")
        if self._remaining(self._command_timeout) <= 0:
            self.close(graceful=False)
            raise TimeoutError(self._diagnostic("Engine run deadline exceeded"))
        try:
            self._check_cancelled()
        except EngineCancelled:
            self.close(graceful=False)
            raise
        self._last_command = cmd
        data = (json.dumps(cmd) + "\n").encode("utf-8")
        with (self.log_dir / "commands.jsonl").open("ab") as log:
            log.write(data)
        started = time.monotonic()
        self._phase = cmd.get("cmd", "request")
        self._commands.put(data)
        try:
            result = self._read(self._remaining(self._command_timeout - (time.monotonic() - started)))
            self._phase = "idle"
            return result
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
            lifecycle = dict(pid=self.proc.pid, exit_code=self.proc.returncode,
                             runtime=self.runtime_version, last_phase=self._phase,
                             graceful_requested=graceful,
                             duration_seconds=round(time.monotonic() - self._launched_at, 3),
                             io_threads_stopped=all(not thread.is_alive() for thread in self._threads))
            try:
                (self.log_dir / "lifecycle.json").write_text(json.dumps(lifecycle), encoding="utf-8")
            except OSError:
                pass
