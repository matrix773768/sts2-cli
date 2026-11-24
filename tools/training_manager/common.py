"""Frozen task specifications and atomic file protocol."""

from contextlib import contextmanager
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from time import sleep
import uuid

from .git_head import checkout_head


ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / "logs" / "inf1"
MODES = ("Full", "Idle", "Light")
SETTINGS = dict(mode="Idle", enabled=True, idle_seconds=600, poll_seconds=1,
                min_disk_mb=2048, min_ram_mb=1536, min_vram_mb=512,
                resource_samples=3, require_ac=True)


def read(path, default=None):
    # Opening a newly replaced file on Windows can briefly produce ERROR_ACCESS_DENIED.
    for attempt in range(10):
        try:
            return json.loads(path.read_bytes())
        except FileNotFoundError:
            return default
        except PermissionError:
            if attempt == 9:
                raise
            sleep(.02)


def write(path, data):
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers can briefly deny replacement.
        for attempt in range(10):
            try:
                temp.replace(path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                sleep(.02)
    finally:
        temp.unlink(missing_ok=True)


def checksum(path):
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(spec):
    data = {key: value for key, value in spec.items() if key != "sha256"}
    return sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def path_at(base, name):
    path = (base / name).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError(f"Path escapes {base}: {name}")
    return path


def home_path(name):
    if HOME.resolve() != HOME:
        raise ValueError("INF1 home must not redirect outside its repository path")
    return path_at(HOME, name)


def number(value, name, minimum, integral=False):
    if type(value) not in ((int,) if integral else (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"Invalid {name}: {value!r}")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value):
        raise ValueError(f"Invalid identifier: {value!r}")
    return value


def settings(home):
    return validate_settings(SETTINGS | read(home / "settings.json", {}))


def validate_settings(cfg):
    if cfg["mode"] not in MODES or type(cfg["enabled"]) is not bool or type(cfg["require_ac"]) is not bool:
        raise ValueError("Invalid settings mode or flag")
    for key in ("idle_seconds", "resource_samples", "min_disk_mb", "min_ram_mb", "min_vram_mb"):
        number(cfg[key], key, 1, integral=True)
    number(cfg["poll_seconds"], "poll_seconds", .1)
    if cfg["poll_seconds"] > 5:
        raise ValueError("poll_seconds must be <= 5")
    return cfg


def output_for(home, spec):
    expected = home / "jobs" / identifier(spec["id"])
    actual = path_at(ROOT, spec["output"])
    if actual != expected:
        raise ValueError(f"Task output must be {expected.relative_to(ROOT)}")
    return actual


def interpreter(name):
    path = Path(name)
    return path.resolve() if path.is_absolute() else path_at(ROOT, name)


def input_path(spec, name):
    return interpreter(name) if name == spec["python"] else path_at(ROOT, name)


def command(spec, stage, work, output, profile):
    args = stage["light_args"] if profile == "Light" and "light_args" in stage else stage["args"]
    values = {"{repo}": str(ROOT), "{work}": str(work), "{output}": str(output)}
    return [str(interpreter(spec["python"])), "-X", "utf8", "-u",
            str(path_at(ROOT, args[0])), *(expand(arg, values) for arg in args[1:])]


def expand(arg, values):
    for key, value in values.items():
        arg = arg.replace(key, value)
    return arg


def verify_assets(spec):
    for name, expected in spec["inputs"].items():
        if checksum(input_path(spec, name)) != expected:
            raise ValueError(f"Input hash changed: {name}")


def validate(spec, home):
    output_for(home, spec)
    if not all(isinstance(spec[k], str) and spec[k].strip() for k in ("name", "type")):
        raise ValueError("Task name and type are required")
    if spec["mode"] not in (*MODES, "Any"):
        raise ValueError("Invalid task mode")
    if spec["sha256"] != identity(spec):
        raise ValueError("Task configuration hash changed")
    if not re.fullmatch(r"[a-f0-9]{40}", spec["baseline"]):
        raise ValueError("Expected a full Git baseline SHA")
    if not path_at(ROOT, spec["cwd"]).is_dir():
        raise ValueError("Task working directory is unavailable")
    python = interpreter(spec["python"])
    if not python.is_file() or python.name.lower() not in ("python.exe", "python"):
        raise ValueError("Task Python executable is unavailable")
    if spec["python"] not in spec["inputs"]:
        raise ValueError("Freeze the Python executable as an input")
    for name, value in spec["inputs"].items():
        input_path(spec, name)
        if not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError(f"Invalid asset hash: {name}")
    number(spec["max_retries"], "max_retries", 0, integral=True)
    if "budget_seconds" in spec:
        number(spec["budget_seconds"], "budget_seconds", 1)
    if "stop_grace_seconds" in spec:
        number(spec["stop_grace_seconds"], "stop_grace_seconds", 1)
    stages = spec["stages"]
    if not isinstance(stages, list) or not stages:
        raise ValueError("At least one stage is required")
    prior = set()
    for stage in stages:
        sid = identifier(stage["id"])
        if sid in prior or not set(stage["depends_on"]) <= prior:
            raise ValueError(f"Repeated stage or forward dependency: {sid}")
        prior.add(sid)
        if stage["resume"] not in ("checkpoint", "restart", "none") or not stage["boundary"].strip():
            raise ValueError(f"Declare checkpoint or restart semantics and stop boundary: {sid}")
        if type(stage["gpu"]) is not bool or type(stage["heavy"]) is not bool:
            raise ValueError(f"Declare GPU needs and interactive load: {sid}")
        number(stage["workers"], "workers", 1, integral=True)
        number(stage.get("stop_grace_seconds", 60), "stop_grace_seconds", 1)
        for key in ("min_ram_mb", "min_disk_mb", "min_vram_mb"):
            number(stage.get(key, 0), key, 0, integral=True)
        for key in ("args", "light_args"):
            if key not in stage and key == "light_args":
                continue
            args = stage[key]
            if not isinstance(args, list) or not args or not all(isinstance(arg, str) and "\0" not in arg for arg in args):
                raise ValueError(f"Expected structured Python arguments: {sid}")
            script = path_at(ROOT, args[0])
            if script.suffix != ".py" or args[0] not in spec["inputs"]:
                raise ValueError(f"Stage script must be a frozen repository input: {sid}")
        if "light_args" in stage:
            number(stage["light_workers"], "light_workers", 1, integral=True)
            if stage["light_workers"] > stage["workers"]:
                raise ValueError(f"Light worker count exceeds normal worker count: {sid}")


def freeze(spec, home):
    result = dict(spec)
    result["baseline"] = checkout_head(ROOT)
    names = set(result["inputs"]) | {result["python"]}
    for stage in result["stages"]:
        names.add(stage["args"][0])
        if "light_args" in stage:
            names.add(stage["light_args"][0])
    result["inputs"] = {name: checksum(input_path(result, name)) for name in sorted(names)}
    result["sha256"] = identity(result)
    validate(result, home)
    return result


@contextmanager
def lease(path):
    """An OS lock released even if its owner dies. The file is never removed."""
    with path.open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False
                return
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
        yield True
