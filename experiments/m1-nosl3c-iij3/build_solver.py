"""Build II-J.3 with shared implicit-all continuation validation."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIJ2 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iij2/build_solver.py"))
IIH = IIJ2["IIH"]


def lifecycle(source):
    IIJ2["lifecycle"](source)
    IIH["edit"](source / "Search/CombatBeamSolver.InteractiveCombat.cs",
        """            if (indices.Count < spec.MinCount || indices.Count > spec.MaxCount ||
""",
        """            // A native implicit-all request consumes the entire available batch.
            // Keep the original declaration for choices exposed to the player.
            int min = spec.IsImplicitAllSelection ? spec.Options.Count : spec.MinCount;
            int max = spec.IsImplicitAllSelection ? spec.Options.Count : spec.MaxCount;
            if (indices.Count < min || indices.Count > max ||
""")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iij.3", subprocess=SimpleNamespace(run=stage)))()
