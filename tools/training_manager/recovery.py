"""Audited copy-forward of committed artifacts into a separately approved task."""

from contextlib import closing
from hashlib import sha256
from pathlib import Path
import shutil
import sqlite3
import sys
from tempfile import TemporaryDirectory

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.training_manager.common import HOME, ROOT, checksum, path_at, read, validate, write
from tools.training_manager.ledger import identity, snapshot
from tools.training_manager.timing import INCIDENT, INCIDENT_JOB, verified_incident


RESTORE = "tools/training_manager/recovery.py"


def admitted(manager):
    if not any(row["id"] == INCIDENT_JOB for row in manager.rows()):
        return None
    row = manager.job(INCIDENT_JOB)
    spec, output, _, _ = manager.inspect(row)
    proof = verified_incident(row, output, spec)
    validate(spec, manager.home)
    runs = manager.report(row, persist=False)["runs"]
    completed = [r["stage"] for r in runs if (r["outcome"] or {}).get("state") == "completed"
                 and r["outcome"].get("exit_code") == 0]
    if completed != proof["completed"] or completed != [s["id"] for s in spec["stages"][:row["stage"]]]:
        raise ValueError("已完成阶段和审计顺序不一致")
    return proof, spec, output


def offer(manager):
    accepted = admitted(manager)
    if not accepted:
        return None
    proof, old, output = accepted
    stages = []
    for stage in old["stages"][len(proof["completed"]):]:
        args = stage["args"]
        if "produce" in args and ("--night-namespace" not in args or
                args[args.index("--night-namespace")+1] != proof["g3"]["seed_namespace"]):
            raise ValueError("续接生产的种子命名空间发生变化")
        stages.append(stage | {"depends_on":["restore", *(dep for dep in stage["depends_on"]
                                                         if dep not in proof["completed"])]})
    restore = dict(id="restore", depends_on=[], args=[RESTORE, "{output}"], gpu=False, heavy=False,
                   workers=1, resume="restart", boundary="已验证的原任务产物复制到独立目录")
    files = [output/"task.json", output/"report.json", INCIDENT]
    plan = {key:value for key,value in old.items() if key not in ("sha256","baseline","budget_seconds")}
    plan.update(id=proof["key"], name="DC2B 夜间任务 G3 续接", output=f"logs/inf1/jobs/{proof['key']}",
                stages=[restore, *stages], inputs=sorted(set(old["inputs"]) | {RESTORE, "tools/training_manager/timing.py"}
                | {p.relative_to(ROOT).as_posix() for p in files}))
    return plan, proof


def verify_compatibility(old, proof):
    replacements = proof["compatible_runtime"]
    for name, expected in old["inputs"].items():
        path = Path(ROOT / name)
        if name in replacements:
            pinned = replacements[name]
            actual = sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            if expected != pinned["original"] or actual != pinned["replacement_lf"]:
                raise ValueError(f"已审核的 INF3 运行时版本不匹配：{name}")
        elif checksum(path) != expected:
            raise ValueError(f"原冻结的研究输入已经改变：{name}")


def approve(manager, seconds):
    prepared, proof = offer(manager)
    _, old, _ = admitted(manager)
    reserve = prepared.get("budget_reserve_seconds", prepared.get("stop_grace_seconds", 180))
    if type(seconds) is not int or seconds <= reserve:
        raise ValueError(f"请输入另行批准的执行预算秒数（大于 {reserve}）。")
    verify_compatibility(old, proof)
    return prepared | {"budget_seconds": seconds, "budget_reserve_seconds": reserve}


def copy_checked(source, target, expected):
    if target.exists():
        if checksum(target) != expected:
            raise ValueError(f"目标产物已有冲突：{target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_name(target.name + ".inf3-copy")
    shutil.copyfile(source, pending)
    if checksum(pending) != expected:
        raise ValueError(f"源产物与审计哈希不匹配：{source}")
    pending.replace(target)


def recover_ledger(source, target, evidence, expected_db, expected_wal, scratch):
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=scratch) as name:
            copy = Path(name) / "results.sqlite"
            copy_checked(source, copy, expected_db)
            if expected_wal:
                copy_checked(source.with_name(source.name+"-wal"), copy.with_name(copy.name+"-wal"), expected_wal)
            temporary = target.with_suffix(".inf3-copy")
            if temporary.exists():
                temporary.unlink()
            with closing(sqlite3.connect(copy)) as db, closing(sqlite3.connect(temporary)) as dest:
                if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ValueError("原 SQLite/WAL 副本未通过完整性检查")
                db.backup(dest)
                dest.execute("PRAGMA journal_mode=DELETE")
            if identity(temporary) != evidence:
                raise ValueError("SQLite 提交集合与审计证据不匹配")
            temporary.replace(target)
    if identity(target) != evidence:
        raise ValueError("已恢复的账本与审计证据不匹配")
    with snapshot(target) as db:
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("续接账本完整性检查失败")


def restore(destination):
    from tools.training_manager.manager import Manager
    manager = Manager(HOME)
    with closing(manager.db):
        proof, old, source = admitted(manager)
    verify_compatibility(old, proof)
    if destination.resolve() != HOME/"jobs"/proof["key"]:
        raise ValueError("续接输出目录与已审核计划不一致")
    locked = read(destination/"task.json")
    validate(locked, HOME)
    if locked["id"] != proof["key"] or locked["inputs"].get(INCIDENT.relative_to(ROOT).as_posix()) != checksum(INCIDENT):
        raise ValueError("续接证据与冻结任务不匹配")
    restore_artifacts(proof, source, destination)


def restore_artifacts(proof, source, destination):
    scratch = destination/"restore"
    scratch.mkdir(parents=True, exist_ok=True)
    files = proof["files"]
    ledger = "g3-direct/ledger/results.sqlite"
    recover_ledger(path_at(source,ledger), path_at(destination,ledger), proof["g3"]["identity"], files[ledger],
                   files.get(ledger+"-wal"), scratch)
    for name, expected in files.items():
        if name in (ledger, ledger+"-wal"):
            continue
        src, target = path_at(source,name), path_at(destination,name)
        if target.name != "progress.json":
            copy_checked(src,target,expected)
            continue
        if checksum(src) != expected:
            raise ValueError(f"原进度与审计哈希不匹配：{src}")
        info = read(src)
        if info.get("checkpoint"):
            info["checkpoint"] = str(destination/Path(info["checkpoint"]).relative_to(source))
        if name == "g3-direct/progress.json":
            count = proof["g3"]["identity"]["count"]
            info.update(done=count, attempts=count, complete=count, throughput=None, measured_units=0)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            write(target,info)
        elif read(target) != info:
            raise ValueError(f"续接进度与已还原产物不一致：{target}")
    write(destination/"restore/summary.json", {"source":proof["source"],"skipped":proof["completed"],
                                               "committed":proof["g3"]["identity"]["count"]})


if __name__ == "__main__":
    restore(Path(sys.argv[1]).resolve())
