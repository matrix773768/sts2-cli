"""Sample engine resident memory and simultaneous batch totals."""
import os
from pathlib import Path
import threading


def _reader():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "peak", "working", "peak_paged", "paged", "peak_nonpaged",
                    "nonpaged", "pagefile", "peak_pagefile",
                )
            ]
        get_memory = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        get_memory.restype = wintypes.BOOL

        def windows(process):
            counters = Counters()
            counters.size = ctypes.sizeof(counters)
            if get_memory(int(process._handle), ctypes.byref(counters), counters.size):
                return counters.working, counters.peak

        return windows
    if Path("/proc/self/status").is_file():
        def linux(process):
            try:
                lines = Path(f"/proc/{process.pid}/status").read_text().splitlines()
                values = {line.split(":")[0]: int(line.split()[1]) * 1024
                          for line in lines if line.startswith(("VmRSS:", "VmHWM:"))}
                return values["VmRSS"], values["VmHWM"]
            except (OSError, KeyError):
                return None
        return linux
    return None


class MemorySampler:
    def __init__(self, interval=0.02):
        self.interval = interval
        self._read = _reader()
        self._processes = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.process_peaks = {}
        self.batch_peak = None
        self.samples = 0

    def add(self, process, log_dir):
        with self._lock:
            self._processes.append((process, str(log_dir)))

    def _sample(self):
        while not self._stop.wait(self.interval):
            with self._lock:
                live = [(p, name) for p, name in self._processes if p.poll() is None]
            readings = [(name, self._read(p)) for p, name in live]
            for name, reading in readings:
                if reading is not None:
                    self.process_peaks[name] = max(self.process_peaks.get(name, 0), reading[1])
            if readings and all(reading is not None for _, reading in readings):
                total = sum(reading[0] for _, reading in readings)
                self.batch_peak = max(self.batch_peak or 0, total)
                self.samples += 1

    def __enter__(self):
        self._thread = None
        if self._read is not None:
            self._thread = threading.Thread(target=self._sample)
            self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
