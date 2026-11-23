"""Run the PRE0 interruption and worker-fault probes against PRE0B."""
import argparse
from pathlib import Path
import runpy
import sys


def command(output, host, count, recycle):
    return [sys.executable, "-X", "utf8", str(Path(__file__).with_name("run.py")),
            str(output), "--host", str(host), "--fast", "--workers", "4", "--count", str(count),
            "--recycle", str(recycle), "--batch-delay", "0", "--buffered-logs"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    args = parser.parse_args()
    previous = Path(__file__).resolve().parent.parent / "m1-pre0/recovery_probe.py"
    probe = runpy.run_path(str(previous))["probe"]
    probe.__globals__["producer_command"] = command
    probe(args.output, args.host, args.reference, committed=64, through=96)
