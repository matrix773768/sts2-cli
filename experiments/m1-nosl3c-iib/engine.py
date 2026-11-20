"""Pinned solver and independently owned worker startup."""
import json
import os
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
HOST = "m1-nosl3c-iib-build"
BINDING = runpy.run_path(str(HERE.parent / "m1-s3a/produce.py"))
BANK = BINDING["bank"]
CAPTURE = BINDING["b1b"].synth.capture


def bind(output, build):
    identity = json.loads((build / "build.json").read_bytes())
    baseline = BANK.versions_for_host(output, HOST)
    dll = (build / "bin/CombatSolver.dll").resolve()
    if (identity["frozen_sha256"] != baseline["solver_sha256"]
            or identity["game_sha256"] != baseline["game_sha256"]
            or BANK.f1.digest(dll.read_bytes()) != identity["patched_sha256"]
            or BANK.f1.digest((HERE / "InteractiveCombat.cs").read_bytes()) != identity["bridge_sha256"]):
        raise ValueError("Unexpected interactive build identity")
    os.environ["I1_SOLVER"] = str(dll)
    return baseline | {"solver": identity["version"], "solver_sha256": identity["patched_sha256"]}


def open_worker(output, stack, versions):
    return BINDING["attested"](output, stack, versions)[0]
