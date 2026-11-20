"""Apply the frozen process-kill recovery test to the bounded optimized runner."""
import argparse
from inspect import getsource
from pathlib import Path
import runpy
import subprocess
import sys

from features import BASE, HERE
from profile_stock import replace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    pilot = BASE / "pilot.json"
    paused = output / "paused"
    driver = output / "comparison"
    output.mkdir(parents=True, exist_ok=False)
    settings = ["--mode", "batched", "--early-dispatch"]
    subprocess.run([sys.executable, str(HERE / "runner.py"), str(paused), "--config", str(pilot),
                    "--through-update", "0", *settings], check=True)
    reference = runpy.run_path(str(BASE / "verify_resume.py"))["interrupt_then_resume"]
    source = replace(getsource(reference), 'str(HERE / "run.py"), str(run), "--config", str(config_path)]',
                     'str(ENTRY), str(run), "--config", str(config_path), *SETTINGS]')
    context = reference.__globals__ | dict(ENTRY=HERE / "runner.py", SETTINGS=settings)
    exec(compile(source, reference.__code__.co_filename, "exec"), context)
    context["interrupt_then_resume"](driver, pilot, paused)


if __name__ == "__main__":
    main()