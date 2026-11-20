"""Build the isolated host with the real Neutralize execution path."""
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
IIG = runpy.run_path(str(HERE.parent / "m1-nosl3c-iig/build_host.py"))
HOST = "m1-nosl3c-iig-completion-build"


def stage(src):
    IIG["stage"](src)
    path = src / "RunSimulator.cs"
    code = path.read_text(encoding="utf-8")
    start = code.index("            // Patch Neutralize.OnPlay to avoid NullRef")
    end = code.index("            // Patch HasEntry to always return true", start)
    code = code[:start] + code[end:]
    path.write_text(code, encoding="utf-8")


if __name__ == "__main__":
    base = IIG["BASE"]["BASE"]["BASE"]["BASE"]["BINDING"].b1b.b1a.i1
    base.build(base.ROOT / "logs" / HOST, stage)
