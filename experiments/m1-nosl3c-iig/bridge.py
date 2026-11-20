"""Rebind II-F audit to the new isolated host, leaving frozen modules on disk."""
from pathlib import Path
from types import FunctionType
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-nosl3c-iif"))
import audit

targets = audit.targets
VERSION = "sts2.nosl.iig.enemy-death-window.v1"
SOLVER = '996082fb217c13a19a4bbd9eb712c0360c7deb6cad39b2f9a43f313ca7c33086'


def bind(output, solver):
    original = targets.bind
    return FunctionType(original.__code__,original.__globals__|{"HOST":"m1-nosl3c-iig-build"})(output,solver)


def certify(output, versions, spec, row, mode="diagnostic"):
    if versions["solver_sha256"] != SOLVER:
        return audit.certify(output,versions,spec,row,mode=mode)
    rule = audit.qualifies
    pinned = FunctionType(rule.__code__,rule.__globals__|dict(SOLVER=SOLVER))
    original = audit.certify
    run = FunctionType(original.__code__,original.__globals__|dict(qualifies=pinned,VERSION=VERSION))
    return run(output,versions,spec,row,mode=mode,worker=None)
