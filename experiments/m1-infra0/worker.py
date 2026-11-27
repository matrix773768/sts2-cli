"""Private subprocess. One instance owns one lane, one model cache and one gzip."""
from time import perf_counter_ns as clock, process_time_ns
ENTRY=clock()
import cProfile
import gc
import gzip
import json
import os
from pathlib import Path
import platform
import sys
import ctypes
from ctypes import wintypes
from infra_assets import ROOT

def resources(handle):
    class Memory(ctypes.Structure):
        _fields_=[("cb",wintypes.DWORD),("PageFaultCount",wintypes.DWORD)]+[(k,ctypes.c_size_t) for k in
            ("PeakWorkingSetSize","WorkingSetSize","QuotaPeakPagedPoolUsage","QuotaPagedPoolUsage",
             "QuotaPeakNonPagedPoolUsage","QuotaNonPagedPoolUsage","PagefileUsage","PeakPagefileUsage")]
    mem=Memory()
    io=(ctypes.c_ulonglong*6)()
    handle=wintypes.HANDLE(handle)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(handle,ctypes.byref(mem),ctypes.sizeof(mem)):
        raise ctypes.WinError()
    if not ctypes.windll.kernel32.GetProcessIoCounters(handle,ctypes.byref(io)):
        raise ctypes.WinError()
    return dict(peak_rss=mem.PeakWorkingSetSize,read_bytes=io[3],write_bytes=io[4])

def run(task):
    folder=Path(task["folder"])
    roots=task["ids"]
    mode=task["mode"]
    os.environ.update(STS2_CORE5D_RUN=str(folder),STS2_CORE5C_HOST=str(ROOT/"logs"/
        ("core5c-host" if mode=="baseline" else "infra0-profile-host")))
    for k in ("TMP","TEMP","TMPDIR","TORCH_HOME","XDG_CACHE_HOME","DOTNET_CLI_HOME"):
        os.environ[k]=str(folder/"tmp")
    sys.path.insert(0,str(ROOT/"experiments/m1-core5d"))
    import battle5d as battle
    import experience5d as pairs
    from panel5d import cohort
    imported=clock()
    meter=None
    if mode!="baseline":
        from meter import Meter
        meter=Meter()
        meter.install(battle,pairs)
    host_io=[]
    close=battle.Lane.close
    def close_lane(lane):
        client=lane.client
        try:return close(lane)
        finally:
            if client:
                handle=int(client.proc._handle)
                stats=resources(handle)
                times=(ctypes.c_ulonglong*4)()
                parts=[ctypes.byref(times,i*8) for i in range(4)]
                if not ctypes.windll.kernel32.GetProcessTimes(wintypes.HANDLE(handle),*parts):raise ctypes.WinError()
                host_io.append(stats|dict(cpu_s=(times[2]+times[3])/1e7))
    battle.Lane.close=close_lane
    diag=cProfile.Profile() if mode=="diagnostic" else None
    closed={}
    boundaries=[]
    def on_record(i):boundaries.append([i,clock()])
    def finish(path):
        with path.open("rb") as f:
            if f.read(2)!=b"\x1f\x8b": raise ValueError("Missing gzip header")
        closed.update(at=clock(),bytes=path.stat().st_size,file=path.name)
    events=None
    if task["smoke"]:
        from semantic_check import observe
        events=observe(battle)
    if diag:diag.enable()
    if task["kind"]=="natural":
        battle.run("train",task["arm"],indices=roots,on_closed=finish,on_record=on_record)
    else:
        pairs.run("train",0,1,indices=set(roots),parents=ROOT/"experiments/m1-core5d/evidence",on_closed=finish,on_record=on_record)
    if diag:
        diag.disable()
        diag.dump_stats(str(folder/"diagnostic.prof"))
    if events is not None:(folder/"semantic.json").write_text(json.dumps(events))
    import torch
    data=dict(entry_ns=ENTRY,imported_ns=imported,closed=closed,done_ns=clock(),python_cpu_ns=process_time_ns(),
              python=platform.python_version(),torch=torch.__version__,threads=torch.get_num_threads(),
              interop=torch.get_num_interop_threads(),gc=gc.get_stats(),python_resources=resources(-1),
              record_flushed_ns=boundaries,host_resources=host_io,host=[json.loads(p.read_bytes()) for p in folder.rglob("infra-host.json")],
              stages=meter.values if meter else {},root_cumulative=meter.roots if meter else [])
    (folder/"worker.json").write_text(json.dumps(data))

if __name__=="__main__":
    run(json.loads(Path(sys.argv[1]).read_bytes()))
