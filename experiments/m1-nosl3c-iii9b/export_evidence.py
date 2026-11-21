"""Export II-I.9B pairing, resume checks, and the regular-host test result."""
from collections import Counter
from contextlib import closing
from hashlib import sha256
import gzip
import json
from pathlib import Path
import re
import runpy
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
LOGS = Path("logs")
BASE = runpy.run_path(str(HERE.parent / "m1-nosl3c-iih9/export_evidence.py"))
read = BASE["read"]
journal = BASE["journal"]
PIN = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii9a/replay.py"))
HOST = LOGS / "iih9-main-host/bin/Debug/net9.0/Sts2Headless.dll"


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def ledger(path):
    identity, snapshots, roots = journal["read"](path)
    return json.loads(identity), snapshots, roots


def proof(folder, step, root):
    data = read(folder / "audit" / f"{step:06d}-{root}.json")
    return BASE["proof_fields"](data) | {key: data[key] for key in (
        "prediction_stop_detail", "boundaries", "mode",
    ) if key in data}


def decision(transition):
    action = transition["action"]
    card = action.get("card")
    hand = transition["observation"]["hand"]
    return dict(action=action, card=hand[card]["id"] if card is not None else None,
                behavior_logp=transition.get("behavior_logp"))


def paired(run, suite, count, engine):
    before, after = [LOGS / f"{prefix}-{suite}" for prefix in ("iih9", run)]
    old_id, _, old = ledger(before / "training.sqlite")
    new_id, _, new = ledger(after / "training.sqlite")
    assert new_id["engine"] == engine and old_id["config"] == new_id["config"]
    assert len(old) == len(new) == count
    data = []
    for a, b in zip(old, new, strict=True):
        phase, step, root, status, spec, rows = b
        assert a[:3] == b[:3] and a[4] == spec
        original, latest = a[5][0] if a[5] else {}, rows[0] if rows else {}
        old_p, new_p = proof(before, step, root), proof(after, step, root)
        assert original.get("behavior") == latest.get("behavior")
        early, late = [row.get("transitions", []) for row in (original, latest)]
        changes = BASE["first_changes"](early, late)
        if len(early) != len(late):
            index = min(len(early), len(late))
            changes["first_unpaired_decision"] = dict(
                index=index, baseline=decision(early[index]) if index < len(early) else None,
                current=decision(late[index]) if index < len(late) else None)
        data.append(dict(
            step=step, root=root, encounter=spec["encounter"], baseline=a[3], classification=status,
            baseline_proof=old_p, proof=new_p,
            baseline_feedback=original.get("feedback"), feedback=latest.get("feedback"),
            first_changes=changes, baseline_last_decision=decision(early[-1]) if early else None,
            regression=bool(old_p.get("terminal_verified") and not new_p.get("terminal_verified")),
        ))
    return dict(config_sha256=new_id["config"], roots=data)


def training(run, engine):
    folders = [LOGS / f"{run}-{name}" for name in ("pair16", "cold", "resume")]
    pair, cold, resumed = [ledger(folder / "training.sqlite") for folder in folders]
    for folder in folders:
        path = (folder / "training.sqlite").resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(path, uri=True)) as db:
            assert db.execute("PRAGMA quick_check").fetchone() == ("ok",)
    assert pair[0]["engine"] == cold[0]["engine"] == resumed[0]["engine"] == engine
    assert cold[2][:16] == resumed[2][:16] == pair[2]
    comparison = read(LOGS / f"{run}-journals.json")
    snapshots = [dict(step=i, sha256=sha, stats=json.loads(gzip.decompress(stats)))
                 for i, sha, _, stats in cold[1]]
    admissions = []
    for _, step, root, status, spec, rows in cold[2]:
        eligible = [row for row in rows if row["feedback"]["eligible"]]
        assert all(row["qualification"]["mode"] == "exact"
                   and row["qualification"]["certification"] == "exact_native_match"
                   for row in eligible)
        admissions.append(dict(step=step, root=root, classification=status, eligible=len(eligible)))
    return dict(comparison=comparison, snapshots=snapshots, admissions=admissions,
                reused_first_batch=True)


def main(run):
    identity, _, _ = ledger(LOGS / f"{run}-pair16/training.sqlite")
    engine = identity["engine"]
    assert (engine["solver_sha256"], engine["headless_sha256"]) == (PIN["SOLVER"], PIN["HOST"])
    assert engine["coreclr"] == "9.0.7" and engine["game"] == "0.113.1/26660232"
    previous = HERE.parent / "m1-nosl3c-iii9a/evidence.json"
    assert read(previous)["engine"] == engine
    tests = LOGS / f"{run}-main-pytest.log"
    summary = next(line for line in reversed(tests.read_text(encoding="utf-8").splitlines())
                   if re.search(r"\b\d+ (passed|failed|errors?)\b", line))
    data = dict(engine=engine, build=read(LOGS / "m1-nosl3c-iii8-candidate/build.json"),
                iii9a=dict(path=previous.relative_to(HERE.parent.parent).as_posix(), sha256=digest(previous)),
                pair16=paired(run, "pair16", 16, engine), holdout=paired(run, "holdout", 60, engine),
                training=training(run, engine),
                main_tests=dict(summary=summary, sha256=digest(HOST), host=HOST.as_posix(),
                                log=tests.as_posix(), log_sha256=digest(tests)))
    for suite in ("pair16", "holdout"):
        rows = data[suite]["roots"]
        print(suite, Counter(r["classification"] for r in rows),
              "regressions", [(r["step"], r["root"]) for r in rows if r["regression"]])
    print(data["training"]["comparison"], summary)
    (HERE / "evidence.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "iii9b")
