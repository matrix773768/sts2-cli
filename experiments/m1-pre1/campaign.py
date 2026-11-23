"""Execute the frozen PRE1 campaign, including the matched transfer controls."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from time import monotonic, sleep


HERE = Path(__file__).resolve().parent
ARCHIVE = Path("logs/m1-pre0-formal-8b/dataset.sqlite")
TEACHER = Path("logs/nosl3c-iii-a2-01/training/training.sqlite")
HOST = Path("logs/m1-pre0b-host-final")
DEV = Path("logs/m1-pre1-dev-freeze/dev.json")
SOURCES = [Path("logs") / f"m1-pre1-data-{arm}" for arm in ("p0","teacher","structured")]


def count(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=30)) as db:
        return db.execute("SELECT count(*), sum(complete), sum(complete AND split='train') FROM trajectories").fetchone()


def wait_corpora(seconds, prefix):
    deadline = monotonic()+seconds
    while True:
        if prefix:
            for path in SOURCES[:2]:
                dataset = path/"dataset.sqlite"
                if dataset.is_file() and not any(path.glob("run-*.json")) and count(dataset)[0] >= prefix:
                    (path/"STOP").touch()
        if all(any(path.glob("run-*.json")) for path in SOURCES):
            break
        if monotonic() >= deadline:
            raise TimeoutError("Production summaries did not reach the preregistered quotas")
        sleep(15)
    datasets = [path/"dataset.sqlite" for path in SOURCES]
    totals = [count(path) for path in datasets]
    if sum(x[1] for x in totals) < 50000:
        raise ValueError(f"New complete corpus below quota: {totals}")
    return datasets, totals


def execute(python, output, log_name, script, *arguments):
    command = [str(python),"-X","utf8",str(HERE/script),*map(str,arguments)]
    with (output/log_name).open("a",encoding="utf-8") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)


def run(output, python, device, seconds, prefix):
    output.mkdir(exist_ok=True)
    if (output/"STOP").exists():
        return
    datasets, totals = wait_corpora(seconds,prefix)
    corpus = dict(archived=str(ARCHIVE), new_sources={})
    for path, (attempts, complete, train) in zip(datasets, totals, strict=True):
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True)) as db:
            source = json.loads(db.execute("SELECT json FROM manifest").fetchone()[0])
        corpus["new_sources"][str(path)] = dict(attempts=attempts, complete=complete, train=train,
                                               synthetic=True, natural_reachability="unverified",
                                               behavior_sha256=source["behavior"], recipe=source["config"]["version"])
    (output/"corpus.json").write_text(json.dumps(corpus,indent=2),encoding="utf-8")
    for dataset in datasets:
        verify = Path("../m1-pre0/verify.py")
        execute(sys.executable,output,f"verify-{dataset.parent.name}.log",verify,dataset)
    features = output/"features"
    execute(sys.executable,output,"prepare.log","prepare.py",features,ARCHIVE,*datasets)
    if device == "auto":
        check = subprocess.run([str(python),"-c","import torch; raise SystemExit(not torch.cuda.is_available())"])
        device = "cuda" if check.returncode == 0 else "cpu"
        if device == "cpu":
            python = sys.executable
    weights = output/"weights"
    completed = weights/"summary.json"
    if completed.exists():
        if json.loads(completed.read_bytes())["epochs"] != 20 or not all(
                (weights/name).is_file() for name in ("final.pt","initial.pt","mechanism.pt","encoder.pt")):
            raise ValueError("Main training completion artifacts are inconsistent")
    else:
        execute(python,output,"train.log","train.py",features,weights,"--device",device)
    if not completed.is_file() or (output/"STOP").exists():
        return
    for mode in ("behavior","transfer"):
        arm = output/f"{mode}-stable"
        if (arm/"summary.json").is_file():
            summary = json.loads((arm/"summary.json").read_bytes())
            if summary["epochs"] != 10 or not (arm/"final.pt").is_file():
                raise ValueError(f"Adaptation completion artifacts are inconsistent: {mode}")
        else:
            options = ["--start-weights",weights/"mechanism.pt"] if mode=="transfer" else []
            execute(python,output,f"control-{mode}-stable.log","train.py",features,arm,
                    "--device",device,"--mode",mode,"--config",HERE/"adapt-schedule.json",*options)
        if not (arm/"summary.json").is_file() or (output/"STOP").exists():
            return
    execute(sys.executable,output,"evaluate.log","evaluate.py",output/"development",
            "--host",HOST,"--manifest",DEV,"--weights",weights,"--teacher",TEACHER,
            "--behavior",output/"behavior-stable/final.pt","--transfer",output/"transfer-stable/final.pt",
            "--additional-grouped","--corpus",ARCHIVE,*datasets)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--python",type=Path,default=Path(sys.executable))
    parser.add_argument("--device",choices=("cpu","cuda","auto"),default="auto")
    parser.add_argument("--wait-seconds",type=float,default=9000)
    parser.add_argument("--stop-at-prefix",type=int,default=0,
                        help="Ask the two random producers to drain after this many committed roots each")
    args = parser.parse_args()
    run(args.output,args.python.resolve(),args.device,args.wait_seconds,args.stop_at_prefix)
