"""Windows process ownership, detachment and resource probes."""

from contextlib import contextmanager
import ctypes as ct
from ctypes import wintypes as wt
import os
from pathlib import Path
import shutil
import subprocess


if os.name == "nt":
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    user = ct.WinDLL("user32", use_last_error=True)

    def api(name, result, *args):
        fn = getattr(kernel, name)
        fn.restype, fn.argtypes = result, args
        return fn

    close = api("CloseHandle", wt.BOOL, wt.HANDLE)
    open_process = api("OpenProcess", wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
    times = api("GetProcessTimes", wt.BOOL, wt.HANDLE, *([ct.POINTER(wt.FILETIME)] * 4))
    wait = api("WaitForSingleObject", wt.DWORD, wt.HANDLE, wt.DWORD)
    current = api("GetCurrentProcess", wt.HANDLE)
    in_job = api("IsProcessInJob", wt.BOOL, wt.HANDLE, wt.HANDLE, ct.POINTER(wt.BOOL))
    create_job = api("CreateJobObjectW", wt.HANDLE, wt.LPVOID, wt.LPCWSTR)
    set_job = api("SetInformationJobObject", wt.BOOL, wt.HANDLE, ct.c_int, wt.LPVOID, wt.DWORD)
    assign = api("AssignProcessToJobObject", wt.BOOL, wt.HANDLE, wt.HANDLE)
    terminate_job = api("TerminateJobObject", wt.BOOL, wt.HANDLE, wt.UINT)
    query_job = api("QueryInformationJobObject", wt.BOOL, wt.HANDLE, ct.c_int, wt.LPVOID, wt.DWORD, wt.LPVOID)
    tick = api("GetTickCount", wt.DWORD)
    system_times = api("GetSystemTimes", wt.BOOL, *([ct.POINTER(wt.FILETIME)] * 3))


class BasicLimits(ct.Structure):
    _fields_ = [("per_process", ct.c_int64), ("per_job", ct.c_int64), ("flags", wt.DWORD),
                ("minimum_working_set", ct.c_size_t), ("maximum_working_set", ct.c_size_t),
                ("active_process", wt.DWORD), ("affinity", ct.c_size_t),
                ("priority", wt.DWORD), ("scheduling", wt.DWORD)]


class ExtendedLimits(ct.Structure):
    _fields_ = [("basic", BasicLimits), ("io", ct.c_uint64 * 6), ("memory", ct.c_size_t * 4)]


class Memory(ct.Structure):
    _fields_ = [("length", wt.DWORD), ("load", wt.DWORD), ("total", ct.c_uint64),
                ("available", ct.c_uint64), ("remaining", ct.c_uint64 * 5)]


class Power(ct.Structure):
    _fields_ = [("ac", ct.c_ubyte), ("flags", ct.c_ubyte), ("percent", ct.c_ubyte),
                ("status", ct.c_ubyte), ("life", wt.DWORD), ("full_life", wt.DWORD)]


class LastInput(ct.Structure):
    _fields_ = [("size", wt.UINT), ("time", wt.DWORD)]


class JobAccounting(ct.Structure):
    _fields_ = [("times", ct.c_int64 * 4), ("faults", wt.DWORD), ("total", wt.DWORD),
                ("active", wt.DWORD), ("terminated", wt.DWORD)]


def checked(ok):
    if not ok:
        raise ct.WinError(ct.get_last_error())
    return ok


def process_identity(pid):
    """Return the PID plus immutable creation stamp for a live process."""
    if os.name != "nt":
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        except (FileNotFoundError, ProcessLookupError):
            return None
        return None if fields[0] == "Z" else {"pid": pid, "created": int(fields[19])}
    handle = open_process(0x101000, False, pid)  # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        stamps = [wt.FILETIME() for _ in range(4)]
        if wait(handle, 0) != 258 or not times(handle, *(ct.byref(stamp) for stamp in stamps)):
            return None
        return {"pid": pid, "created": (stamps[0].dwHighDateTime << 32) | stamps[0].dwLowDateTime}
    finally:
        close(handle)


@contextmanager
def process_tree():
    if os.name != "nt":
        raise ValueError("INF1 process-tree supervision requires Windows")
    job = checked(create_job(None, None))
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        checked(set_job(job, 9, ct.byref(limits), ct.sizeof(limits)))
        yield job
    finally:
        close(job)


def attach(job, pid):
    process = checked(open_process(0x101, False, pid))  # PROCESS_TERMINATE | PROCESS_SET_QUOTA
    try:
        checked(assign(job, process))
    finally:
        close(process)


def drain(job):
    from time import sleep
    checked(terminate_job(job, 1))
    stats = JobAccounting()
    while True:
        checked(query_job(job, 1, ct.byref(stats), ct.sizeof(stats), None))
        if not stats.active:
            return
        sleep(.05)


def detach(command, cwd, log):
    flags = 0x8 | subprocess.CREATE_NEW_PROCESS_GROUP  # DETACHED_PROCESS
    belongs = wt.BOOL()
    checked(in_job(current(), None, ct.byref(belongs)))
    if belongs.value:
        flags |= 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
    return subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                            creationflags=flags)


def cpu_times():
    if os.name != "nt":
        return None
    clocks = [wt.FILETIME() for _ in range(3)]
    if not system_times(*(ct.byref(clock) for clock in clocks)):
        return None
    idle, kernel_time, user_time = [(clock.dwHighDateTime << 32) | clock.dwLowDateTime for clock in clocks]
    return idle, kernel_time + user_time


def resources(path, gpu=False):
    values = dict(ram_mb=None, disk_mb=shutil.disk_usage(path).free // 2**20, ac=None, idle_seconds=None,
                  gpu_available=None, gpus=None)
    if os.name != "nt":
        return values
    memory, power, last = Memory(), Power(), LastInput()
    memory.length, last.size = ct.sizeof(memory), ct.sizeof(last)
    if kernel.GlobalMemoryStatusEx(ct.byref(memory)):
        values["ram_mb"] = memory.available // 2**20
    if kernel.GetSystemPowerStatus(ct.byref(power)) and power.ac in (0, 1):
        values["ac"] = bool(power.ac)
    if user.GetLastInputInfo(ct.byref(last)):
        values["idle_seconds"] = ((tick() - last.time) & 0xffffffff) / 1000
    if gpu:
        try:
            result = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.free,memory.used,utilization.gpu,temperature.gpu,power.draw",
                 "--format=csv,noheader,nounits"], timeout=4, text=True, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            names = ("name", "free_mb", "used_mb", "utilization_pct", "temperature_c", "power_w")
            values["gpus"] = [
                {key: value if key == "name" else float(value) if value.replace(".", "", 1).isdigit() else None
                 for key, value in zip(names, (part.strip() for part in line.split(",")))}
                for line in result.splitlines() if line.strip()
            ]
            values["gpu_available"] = bool(values["gpus"])
        except (OSError, subprocess.SubprocessError):
            pass
    return values
