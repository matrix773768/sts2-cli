"""Build the II-H.8 Solver for the independent Headless replay."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIH6 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iih6/build_solver.py"))
IIH = IIH6["IIH"]


def lifecycle(source):
    IIH6["lifecycle"](source)
    turn = source / "Search/CombatBeamSolver.TurnExecutionContinuation.cs"
    IIH["edit"](turn, """        using var beforeChoice = !progress.SideStarted && stage <= PlayerStartStage.AfterPlayer
            ? choices.BeforeNextTake(StartSide) : null;""", """        // Headless card selection awaits the selector without signaling a hook
        // pause. Complete player setup (including selection effects) before side start.""")
    IIH["edit"](turn, "        beforeChoice?.Dispose();\n", "")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iih.8.1", subprocess=SimpleNamespace(run=stage)))()
