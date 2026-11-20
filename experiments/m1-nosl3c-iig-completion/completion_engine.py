"""Keep the new host and certification lineage separate from the frozen II-G runs."""
from pathlib import Path
import sys
from types import FunctionType

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iig"))
import bridge as iig

targets = iig.targets
RULE = "sts2.nosl.iig.completion.enemy-death-window.v1"
ATTESTED_SOLVER = "8d1c9786f88e9057bbdf5d2cf7298cafd52f23b7db532b7ea295d7280f02c41d"


def bind(output, solver):
    original = targets.bind
    bound = FunctionType(original.__code__, original.__globals__ |
                         {"HOST": "m1-nosl3c-iig-completion-build"})
    return bound(output, solver)


def certify(output, versions, spec, row, mode="diagnostic"):
    audit = iig.audit
    check = audit.qualifies
    checked = FunctionType(check.__code__, check.__globals__ | {"SOLVER": ATTESTED_SOLVER})
    original = audit.certify
    isolated = FunctionType(original.__code__, original.__globals__ | dict(qualifies=checked, VERSION=RULE))
    return isolated(output, versions, spec, row, mode=mode, worker=None)
