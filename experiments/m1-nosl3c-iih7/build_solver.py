from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIH6 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iih6/build_solver.py"))
IIH = IIH6["IIH"]

if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iih.7.1", subprocess=SimpleNamespace(run=IIH6["stage"])))()
