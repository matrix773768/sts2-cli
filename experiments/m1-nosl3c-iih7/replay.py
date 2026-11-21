from pathlib import Path
import runpy
import sys
from types import FunctionType

from build_host import HOST

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iih3"))
from certification import bind as bind_iih3


def bind(output, solver):
    original = bind_iih3
    return FunctionType(original.__code__, original.__globals__ | {"HOST": HOST})(output, solver)


if __name__ == "__main__":
    main = runpy.run_path(str(HERE.parent / "m1-nosl3c-iih3/replay.py"))["main"]
    FunctionType(main.__code__, main.__globals__ | {"bind": bind})()
