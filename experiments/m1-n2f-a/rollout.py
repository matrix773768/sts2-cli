"""One independently rebuilt root per NOSL rollout, with append-only budget accounting."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

from study_design import HERE, ROOT, IDENTITY_KEYS, digest, file_hash, read, save

sys.path.insert(0, str(HERE.parent / "m1-n2d"))
from run_factorial import n2b, root_audit
from native_interaction import audit

NORMAL = ("predicted_win", "death")


def rows(path):
    if path.exists():
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return []


def append(path, record):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")


def qualify_audit(output):
    audits = rows(output / "native.jsonl")
    if len(audits) != 4:
        raise ValueError("Four prespecified native audit rows required")
    for row in audits:
        status = row.get("status")
        predicted = row.get("predicted_terminal")
        native = row.get("native_locked", {})
        if not predicted or not status or status in {"native_error", "native_rejected"}:
            raise ValueError(f"Native audit incomplete: {row['id']} {status}")
        expected_status = "win" if predicted["hp"] > 0 else "death"
        if status != expected_status or (status == "win" and native.get("player_hp") != predicted["hp"]):
            raise ValueError(f"Audit detected a label-changing difference: {row['id']}")
    return audits


def execute_candidate(output, phase, item, versions, prediction, cap):
    base = n2b.base
    tick = perf_counter()
    lifecycle = []
    key = item["case"]["id"]
    try:
        expected = {"root_sha256": prediction["lifecycle"]["root_sha256"]} if phase == "audit" else {}
        with base.worker(output, item | expected, versions, lifecycle) as (game, surface):
            if phase == "audit":
                if root_audit(surface) != prediction["root_audit"]:
                    raise ValueError("Root RNG audit differs")
                row = audit(game, surface["public_root"], prediction)
            else:
                game.n2a2_cap = cap
                row = base.execute(game, item, False, phase)
                row.update(root_audit=root_audit(surface))
    except (base.bank.f1.i2.StopRun, ValueError, TimeoutError) as error:
        row = dict(terminal=dict(status="execution_error" if lifecycle else "build_error",
                                 detail=str(error)), trajectory=[])
    return dict(row, phase=phase, id=key, lifecycle=lifecycle[0] if lifecycle else None,
                wall_ms=base.ms(tick), evidence=row.get("evidence", "prediction_only"))


def text_hash(path):
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def verify_model_lock(output):
    model = read(output / "models.json")
    signature = model.pop("sha256")
    if (signature != digest(model) or model["protocol_sha256"] != digest(read(HERE / "protocol.json"))
            or model["model_code_sha256"] != text_hash(HERE / "learning.py")):
        raise ValueError("Report roots require a valid model lock")


def training_qualification(counts, expected, stop):
    normal = sum(counts.get(status, 0) for status in NORMAL)
    coverage = normal / expected
    minority = min(counts.get(status, 0) for status in NORMAL) / max(normal, 1)
    return dict(normal=normal, expected=expected, coverage=coverage, minority=minority,
                passed=(sum(counts.values()) == expected and coverage >= stop["min_train_coverage"]
                        and minority >= stop["min_class_fraction"]))


def require_training_feedback(ledger, cases, config):
    ids = {item["case"]["id"] for item in cases if item["case"]["cohort"] == "train"}
    counts = Counter(r["terminal"]["status"] for r in ledger if r["id"] in ids)
    qualification = training_qualification(counts, len(ids), config["stop"])
    if not qualification["passed"]:
        raise SystemExit(f"Frozen training feedback gate failed: {qualification}")
    return dict(counts)


def run(output, phase):
    output.mkdir(parents=True, exist_ok=True)
    with n2b.base.bank.writer(output):
        run_locked(output, phase)


def run_locked(output, phase):
    config = read(HERE / "protocol.json")
    cases = read(HERE / "manifest.json")
    if digest(cases) != config["manifest_sha256"]:
        raise ValueError("Manifest digest differs")
    normalized = read(HERE / "source-content.json")
    for name, expected in config["source_hashes"].items():
        path = name.replace(chr(92), "/")
        if file_hash(ROOT / path) != expected and text_hash(ROOT / path) != normalized[path]:
            raise ValueError(f"Frozen source differs: {path}")
    if phase == "report":
        verify_model_lock(output)
    ledger = output / "ledger.jsonl"
    journal = output / "budget.jsonl"
    prior = rows(journal)
    spent = {(r["phase"], r["id"]) for r in prior}
    if len(spent) != len(prior):
        raise ValueError("Duplicate budget reservation")
    previous_rows = rows(ledger)
    by_id = {row["id"]: row for row in previous_rows}
    if phase != "train":
        require_training_feedback(previous_rows, cases, config)
    if phase in ("selection", "report"):
        qualify_audit(output)
    base = n2b.base
    versions = base.s3a.solver_binding(output, base.s3a.FIXED, ROOT / "logs/m1-e3f/release")
    if any(versions[k] != config["versions"][k] for k in IDENTITY_KEYS):
        raise ValueError("Bound host differs from protocol")
    base.Episode = n2b.BudgetEpisode
    base.choose = lambda obs, actions, _: n2b.decide(obs, actions, config["policy"]["weights"])
    save(output / "versions.json", versions)
    started = perf_counter()
    target = output / "native.jsonl" if phase == "audit" else ledger
    recorded = {r["id"] for r in rows(target)}
    candidates = []
    for item in cases:
        c = item["case"]
        key = c["id"]
        if phase == "audit":
            if not (c["template"].endswith("-train-0") and c["spec"]["encounter"] == "BOWLBUGS_WEAK"
                    and c["pair"] == digest([config["domain"], c["template"], c["spec"]["encounter"], 0])
                    and c["slot_a"] == c["slot_b"]):
                continue
            prediction = by_id[key]
            if prediction["terminal"]["status"] not in NORMAL:
                append(output / "native-skips.jsonl", dict(id=key, reason=prediction["terminal"]["status"]))
                continue
        elif c["cohort"] != phase:
            continue
        if (phase, key) in spent:
            if key not in recorded:
                append(target, dict(id=key, phase=phase, evidence="prediction_only",
                                    terminal=dict(status="interrupted", detail="Reserved without a completed record"),
                                    trajectory=[]))
            continue
        candidates.append(item)
    if len(spent) + len(candidates) > config["execution_budget"]:
        raise ValueError("Rollout budget exhausted")
    for position, item in enumerate(candidates, 1):
        key = item["case"]["id"]
        append(journal, dict(phase=phase, id=key))
        row = execute_candidate(output, phase, item, versions, by_id.get(key), config["action_cap"])
        append(target, row)
        if position % 16 == 0:
            print(phase, position, "/", len(candidates), flush=True)
    append(output / "timings.jsonl", dict(phase=phase, wall_ms=base.ms(started)))
    if phase == "audit":
        qualify_audit(output)
    if phase == "train":
        print(require_training_feedback(rows(ledger), cases, config), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("phase", choices=["train", "selection", "audit", "report"])
    args = parser.parse_args()
    run(args.output.resolve(), args.phase)
