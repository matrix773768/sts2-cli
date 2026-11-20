"""Stage the bounded NOSL3C worker on the NOSL3A and B1A interfaces."""
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
BASE = runpy.run_path(str(HERE.parent / "m1-nosl3a/build.py"))
HOST = "m1-nosl3c-build"


def stage(src):
    BASE["stage"](src)
    edit = BASE["N2A"]["s3a"].edit
    edit(src / "RealCombat.cs", '            case "f1_begin":', '''            case "f1_3c_release":
                _ledger?.Dispose();
                _ledger = null;
                _combat = null;
                _terminal = null;
                _choices = null;
                return new() { ["type"] = "released" };
            case "f1_begin":''')
    edit(src / "IntegrationProbe.cs", '        if (command == "i1_release")', '''        if (command == "i1_release" && _episode != null)
            throw new InvalidOperationException("Close prediction episode before native release");
        if (command == "i1_release")''')


def main():
    i1 = BASE["N2A"]["s3a"].b1b.b1a.i1
    i1.build(i1.ROOT / "logs" / HOST, stage)


if __name__ == "__main__":
    main()