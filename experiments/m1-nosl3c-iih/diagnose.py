"""Join frozen native replay, continuation, and Solver risk evidence by route."""
import argparse
from collections import Counter
from contextlib import closing
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

COMPLETION = Path(__file__).resolve().parent.parent / "m1-nosl3c-iig-completion"
WITNESSES = {"rule_risk", "semantic_mismatch", "solver_execution_risk"}


def indexed_probes(evidence, name):
    return {(row["ledger"], row["step"], row["root"]): row
            for row in evidence[name]["results"]}


def archived_routes(folder):
    db_uri = (folder / "training.sqlite").resolve().as_uri()
    with closing(sqlite3.connect(db_uri + "?mode=ro", uri=True)) as db:
        for step, position, blob in db.execute("SELECT step,root,rows FROM roots"):
            batch = json.loads(gzip.decompress(blob))
            route = next(iter(batch["rows"]), {}).get("transitions", [])
            yield (step, position), route


def diagnose(ledgers):
    archive_bytes = (COMPLETION / "paired-archive.json.gz").read_bytes()
    evidence_bytes = (COMPLETION / "evidence.json").read_bytes()
    archive = json.loads(gzip.decompress(archive_bytes))
    evidence = json.loads(evidence_bytes)
    original = indexed_probes(evidence, "original_risks")
    terminal = indexed_probes(evidence, "e3")
    folders = {folder.name: folder for folder in ledgers}
    if len(folders) != len(ledgers) or folders.keys() != archive["rows"].keys():
        raise ValueError("Supply each of the three frozen ledger directories once")
    witnesses = []
    coverage = Counter()
    for ledger, rows in archive["rows"].items():
        routes = dict(archived_routes(folders[ledger]))
        for row in rows:
            category = row["native_classification"]
            coverage[category] += 1
            if category not in WITNESSES:
                continue
            key = row["step"], row["position"]
            route = routes[key]
            if len(route) != row["archived_actions"]:
                raise ValueError(f"Archived action count changed for {ledger} {key}")
            probe_key = (ledger, *key)
            prefix = row.get("independent_prefix") or {}
            victory = terminal.get(probe_key, {})
            result = row.get("result") or {}
            trace = row.get("trace") or []
            stop = trace[-1] if trace else {}
            steps = prefix.get("steps") or []
            fields = (prefix.get("differences") or victory.get("fields")
                      or result.get("continuation_fields") or {})
            comparison_position = prefix.get("position", victory.get("initial_position"))
            comparison_action = steps[-1].get("action") if steps else None
            card_id = None
            if (comparison_action and comparison_action.get("card") is not None
                    and comparison_position is not None and 0 <= comparison_position < len(route)):
                hand = route[comparison_position]["observation"]["hand"]
                card_id = hand[comparison_action["card"]]["id"]
            witnesses.append(dict(
                ledger=ledger, step=key[0], position=key[1], root_sha256=row["root"],
                spec=row["spec"], classification=category,
                archived_public_actions=[dict(action=item["action"], observation=item["observation"])
                                         for item in route],
                first_continuation_comparison_position=comparison_position,
                comparison_action=comparison_action, comparison_card_id=card_id,
                certification_first_failure=result.get("first_failure"),
                comparison_status=prefix.get("status", victory.get("status")),
                native_state=prefix.get("native"), predicted_status=prefix.get("predicted"),
                native_terminal=prefix.get("native_terminal"),
                boundary_reason=stop.get("boundary", row.get("latest_boundary")),
                prediction_risk_reasons=stop.get("risk_reasons"),
                prediction_gaps=stop.get("gap_keys"),
                stop_trace=stop, continuation_differences=fields,
                certification_detail=result.get("detail"), comparison_detail=prefix.get("detail"),
                last_stable_boundary=row.get("stable_boundary"),
                native_terminal_windows=victory.get("windows"),
                original_solver_replay=original.get(probe_key),
                settlement_effect="unverified",
            ))
    return dict(schema="sts2.nosl.iih.diagnostic.v1", archive=archive["summary"]["versions"],
                original_solver=evidence["original_risks"]["engine"],
                terminal_probe=evidence["e3"]["engine"],
                sources=dict(paired_archive_sha256=sha256(archive_bytes).hexdigest(),
                             evidence_sha256=sha256(evidence_bytes).hexdigest()),
                coverage=coverage, witnesses=witnesses)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("ledgers", nargs=3, type=Path)
    args = parser.parse_args()
    report = diagnose(args.ledgers)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
