"""OS high-water working set for the evaluation process and its native lane (Windows)."""
from ctypes import Structure,byref,c_uint32,c_size_t,sizeof,windll,c_void_p
class Counters(Structure):
    _fields_=[("cb",c_uint32),("faults",c_uint32)]+[(k,c_size_t) for k in (
       "peak","working","peak_paged","paged","peak_nonpaged","nonpaged","pagefile","peak_pagefile")]
def peak(handle=None):
    c=Counters()
    c.cb=sizeof(c)
    proc=c_void_p(handle if handle is not None else -1)
    if not windll.psapi.GetProcessMemoryInfo(proc,byref(c),c.cb):
        raise OSError("GetProcessMemoryInfo")
    return c.peak
