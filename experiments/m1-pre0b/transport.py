"""Buffered private transport logs for PRE0B's isolated native processes."""
import json
import time


def buffered_client(base, cancelled_type):
    class BufferedClient(base):
        def _drain(self, stream, filename):
            try:
                with (self.log_dir / filename).open("wb", buffering=65536) as log:
                    for line in iter(stream.readline, b""):
                        log.write(line)
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

        def _send(self, cmd):
            if self._closed:
                raise RuntimeError("Engine client is closed")
            if self._remaining(self._command_timeout) <= 0:
                self.close(graceful=False)
                raise TimeoutError(self._diagnostic("Engine run deadline exceeded"))
            try:
                self._check_cancelled()
            except cancelled_type:
                self.close(graceful=False)
                raise
            self._last_command = cmd
            data = (json.dumps(cmd) + "\n").encode("utf-8")
            if getattr(self, "_command_log", None) is None:
                self._command_log = (self.log_dir / "commands.jsonl").open("ab", buffering=65536)
            self._command_log.write(data)
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

        def _close(self, graceful):
            try:
                super()._close(graceful)
            finally:
                log = getattr(self, "_command_log", None)
                if log is not None:
                    log.close()
                    self._command_log = None

    return BufferedClient
