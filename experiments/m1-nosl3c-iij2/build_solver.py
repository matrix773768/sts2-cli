"""Preserve the native Guards selection declaration in the isolated Solver."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIJ1 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iij1/build_solver.py"))
IIH = IIJ1["IIH"]


def lifecycle(source):
    IIJ1["lifecycle"](source)
    search = source / "Search"
    IIH["edit"](search / "CardChoiceSupport.cs",
        "0, owner.Hand.Cards.Count, owner.Hand.Cards,",
        "GuardsSelectionBounds.Value.Min, GuardsSelectionBounds.Value.Max, owner.Hand.Cards,")
    (search / "GuardsSelectionBounds.cs").write_text(
        (HERE / "GuardsSelectionBounds.cs").read_text(encoding="utf-8"), encoding="utf-8")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iij.2", subprocess=SimpleNamespace(run=stage)))()
