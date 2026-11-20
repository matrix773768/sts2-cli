"""Low-frequency Windows process-tree wall, CPU and working-set measurement."""
import ctypes as c
from ctypes import wintypes as wt
import os
from threading import Event, Lock, Thread
from time import perf_counter, process_time


class Memory(c.Structure):
    _fields_ = [("size", wt.DWORD), ("faults", wt.DWORD)] + [
        (name, c.c_size_t) for name in ("peak", "rss", "quota_peak", "quota", "other_peak",
                                        "other", "pagefile", "peak_pagefile")
    ]


class Meter:
    def __init__(self):
        self.lock, self.stop = Lock(), Event()
        self.active, self.retired = {}, 0.
        self.peak = self.phase_peak = 0
        self.cores = os.cpu_count()
        self.kernel = self.psapi = None
        if os.name == "nt":
            self.kernel, self.psapi = c.WinDLL("kernel32"), c.WinDLL("psapi")
            self.kernel.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
            self.kernel.OpenProcess.restype = wt.HANDLE
            self.kernel.CloseHandle.argtypes = (wt.HANDLE,)
            self.kernel.GetProcessTimes.argtypes = (wt.HANDLE,) + (c.POINTER(wt.FILETIME),) * 4
            self.psapi.GetProcessMemoryInfo.argtypes = (wt.HANDLE, c.POINTER(Memory), wt.DWORD)
            self.add(os.getpid())

    def add(self, pid):
        if self.kernel:
            handle = self.kernel.OpenProcess(0x0410, False, pid)
            if not handle:
                raise OSError(f"Could not open measurement handle for PID {pid}")
            with self.lock:
                self.active[pid] = handle

    def read_process(self, handle):
        dates = [wt.FILETIME() for _ in range(4)]
        memory = Memory(size=c.sizeof(Memory))
        cpu = 0.
        if self.kernel.GetProcessTimes(handle, *(c.byref(d) for d in dates)):
            cpu = sum((d.dwHighDateTime << 32) + d.dwLowDateTime for d in dates[2:]) / 1e7
        rss = memory.rss if self.psapi.GetProcessMemoryInfo(handle, c.byref(memory), memory.size) else 0
        return cpu, rss

    def retire(self, pid):
        if self.kernel:
            with self.lock:
                handle = self.active.pop(pid)
                self.retired += self.read_process(handle)[0]
                self.kernel.CloseHandle(handle)

    def snapshot(self):
        with self.lock:
            if self.kernel:
                readings = [self.read_process(handle) for handle in self.active.values()]
                cpu = self.retired + sum(reading[0] for reading in readings)
                rss = sum(reading[1] for reading in readings)
                self.peak = max(self.peak, rss)
                self.phase_peak = max(self.phase_peak, rss)
            else:
                cpu = process_time()
            return perf_counter(), cpu

    def start_phase(self):
        with self.lock:
            self.phase_peak = 0
        return self.snapshot()

    def end_phase(self, start):
        t, cpu = self.snapshot()
        wall = t - start[0]
        used = cpu - start[1]
        return dict(wall_s=wall, cpu_s=used, occupied_cores=used/wall,
                    total_cpu_pct=100*used/(wall*self.cores) if self.cores else None,
                    sampled_peak_rss_mb=self.phase_peak/2**20 if self.kernel else None)

    def __enter__(self):
        def poll():
            while not self.stop.wait(.2):
                self.snapshot()
        self.thread = Thread(target=poll, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        for pid in list(self.active):
            self.retire(pid)