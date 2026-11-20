"""Package archived, resampled and independent qualification evidence separately."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


def read(path):
    return json.loads(path.read_bytes())


def write(path, data):
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(text.encode(), mtime=0))
    else:
        path.write_text(text, encoding="utf-8")


def group(rows, attribute, status):
    grouped = defaultdict(Counter)
    for row in rows:
        grouped[str(attribute(row))][status(row)] += 1
    return dict(grouped)


def qualify_batch(directory, include_public_trajectory=False):
    connection = sqlite3.connect((directory / "training.sqlite").as_uri() + "?mode=ro", uri=True)
    rows = []
    with closing(connection):
        for step, key, raw in connection.execute("SELECT step,root,rows FROM roots ORDER BY step,root"):
            batch = json.loads(gzip.decompress(raw))
            proof = read(directory / "audit" / f"{step:06d}-{key}.json")
            trajectory = next(iter(batch["rows"]), {})
            steps = trajectory.get("transitions", [])
            choices = Counter((t["observation"]["decision"]["pile"], t["observation"]["decision"]["effect"])
                              for t in steps if t["action"]["kind"] == "confirm_selection")
            row = dict(
                step=step, root=key, spec=batch["spec"], constructed=batch["constructed"],
                status=batch["status"], prediction=trajectory.get("feedback"),
                qualification=trajectory.get("qualification"), reason=proof.get("reason"),
                detail=proof.get("detail"), first_failure=proof.get("first_failure"),
                continuation_fields=proof.get("continuation_fields"), decision_count=len(steps),
                choices=[dict(pile=pile, effect=effect, count=n) for (pile, effect), n in sorted(choices.items())],
                multiple_enemies=any(len(t["observation"]["enemies"]) > 1 for t in steps),
                route_digest=proof.get("route"))
            if include_public_trajectory:
                row.update(behavior=trajectory.get("behavior"), public_trajectory=steps)
            rows.append(row)
    return rows


def export(logs, solver, output):
    def run(name):
        return logs / f"nosl3c-iig-completion-{name}"

    def reports(name, filename):
        return read(run(name) / filename)

    archive_meta = reports("archive", "summary.json")
    ledgers = {key: reports("archive", key + ".json") for key in archive_meta["ledgers"]}
    assert sum(map(len, ledgers.values())) == 65
    prefix_reports = {}
    for name in ("final-prefix", "risk-native"):
        for result in reports(name, "prefix.json")["results"]:
            prefix_reports[result["ledger"], result["step"], result["root"]] = result
    for name, ledger in ledgers.items():
        for row in ledger:
            row["independent_prefix"] = prefix_reports.get((name, row["step"], row["position"]))
    rows = [row for ledger in ledgers.values() for row in ledger]
    spec = lambda row, key: row["spec"][key]
    archived_status = lambda row: row["native_classification"]
    keys = ("character", "act", "encounter")
    archive_meta["groups"] = {key: group(rows, lambda row: spec(row, key), archived_status) for key in keys}
    write(output / "paired-archive.json.gz", dict(summary=archive_meta, rows=ledgers))

    batches = {name: qualify_batch(run(name), include_public_trajectory=name == "resample")
               for name in ("resample", "pair16", "independent")}
    batches["resume"] = qualify_batch(run("release-resume"))
    assert tuple(map(len, batches.values())) == (14, 16, 60, 6)
    for row, label in zip(batches["resample"], reports("resample", "resampling-roots.json"), strict=True):
        assert row["spec"] == label["spec"]
        row["original_attempt"] = {k: v for k, v in label.items() if k != "spec"}
    counts = {
        name: {"status": Counter(row["status"] for row in batch),
               "by": {key: group(batch, lambda row: spec(row, key), lambda row: row["status"]) for key in keys}}
        for name, batch in batches.items()
    }
    write(output / "new-trajectories.json.gz", dict(summary=counts, rows=batches))

    names = ("CombatBeamSolver.InteractiveCombat.cs", "CardChoiceSupport.cs", "TurnStartChoiceSupport.cs",
             "TurnStartPowerSupport.cs", "CombatPredictionSimulator.ExecutionContinuation.cs",
             "CombatPredictionHistory.ExecutionContinuation.cs", "PredictionStateStore.CardContinuation.cs",
             "CombatBeamSolver.ExecutionChoiceContinuation.cs", "SimulatedCombatState.ActionChoices.cs",
             "CardEffectSpecRegistry.cs", "SimulatedCombatState.cs")
    source = solver / "source/src"
    hashes = {p.relative_to(source).as_posix(): sha256(p.read_bytes()).hexdigest()
              for p in source.rglob("*.cs") if p.name in names}
    assert len(hashes) == len(names)
    native_compatibility = {path.parent.name: read(path) for path in
                            run("native-regression").glob("*/results.json")}
    assert len(native_compatibility) == 5 and all(
        len(results) == 5 and all(result["completed"] for result in results)
        for results in native_compatibility.values())
    current = ("ambiguous.json", "direct.json", "equivalence.json", "full.json", "reveal.json", "targets.json")
    write(output / "evidence.json", dict(
        schema="sts2.nosl.iig.completion.evidence.v1", build=read(solver / "build.json"), source_hashes=hashes,
        archived=archive_meta["ledgers"], new={name: data["status"] for name, data in counts.items()},
        draw_instances=reports("draw-instances", "draw-instances.json"),
        original_solver=reports("original", "original.json"),
        original_risks=reports("original-risk", "original-risk.json"),
        e3=reports("terminal-windows", "terminal-windows.json"),
        previous_probes={name: reports("current", name) for name in current},
        certification=read(logs / "nosl3c-iig-completion-rule-check.json"),
        native_compatibility=native_compatibility,
        v4=dict(comparison=reports("release-resume", "comparison.json"),
                final=reports("release-resume", "report.json"),
                resampled_update=reports("resample-update", "report.json"))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path)
    parser.add_argument("solver", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.logs.resolve(), args.solver.resolve(), args.output.resolve())
