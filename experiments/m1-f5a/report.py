"""Extract per-root costs and compare independently generated S2C label sets."""
import argparse
from collections import Counter
from pathlib import Path

from probe import HERE, bank, s2c


def evidence(label):
    # Exclude observation clocks and scratch-directory names from equality.
    fields = {
        "hot_ms", "cpu_ms", "replay_ms", "frame_audit_ms", "menu_ms", "rollout_ms",
        "peak_working_set_bytes", "elapsed_ms", "wall_ms", "capture_wall_ms",
        "native_ms", "search_rpc_ms", "prediction_prepare_ms", "quality_ms",
        "quality_hot_ms", "quality_peak_bytes", "evidence_origin", "origin", "ms", "solve_ms",
    }
    if isinstance(label, dict):
        return {k: evidence(v) for k, v in label.items() if k not in fields}
    if isinstance(label, list):
        return [evidence(v) for v in label]
    return label


def distribution(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    pos = .9 * (len(values) - 1)
    low = int(pos)
    return s2c.distribution(values) | {
        "p90": round(values[low] + (pos - low) * (values[min(low + 1, len(values) - 1)] - values[low]), 3)
    }


def extract(directory, selection, versions):
    contract = bank.read(directory / "contract.json")
    if (contract["source_plan_sha256"] != selection["source_plan_sha256"]
            or contract["cap"] != selection["cap"] or contract["algorithm"] != "compare"):
        raise ValueError("Incompatible label contract")
    labels = {}
    for case in selection["selection"]:
        pair = {}
        for policy in selection["policies"]:
            label_id = s2c.s2b.label_id(case["id"], policy, contract["cap"], versions,
                                        contract["implementation"])
            label = s2c.s2b.checked(directory / "labels" / f"{label_id}.json.gz")
            s2c.f3a.equal("label identity", (label_id, case["id"], case["root_id"], policy),
                          (label["id"], label["case_id"], label["root_id"], label["policy"]))
            pair[policy] = label
        labels[case["id"]] = pair
    return contract, labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("fresh", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--retry", type=Path)
    args = parser.parse_args()
    selection = bank.read(HERE / "selection.json")
    plan = s2c.s2b.prepare_plan(s2c.ROOT / "logs/m1-s2b/formal")
    ref_contract, reference = extract(args.reference, selection, plan["versions"])
    contract, fresh = extract(args.fresh, selection, plan["versions"])
    s2c.f3a.equal("identical search implementation", ref_contract["implementation"], contract["implementation"])
    _, roots = s2c.inputs(s2c.ROOT / "logs/m1-s2b/formal", selection, "all")
    retry = {}
    if args.retry:
        failed = [case for case in selection["selection"]
                  if fresh[case["id"]]["f3b"]["level"] != "L3"]
        retry_contract, retry = extract(args.retry, selection | {"selection": failed}, plan["versions"])
        s2c.f3a.equal("retry search implementation", contract["implementation"],
                      retry_contract["implementation"])
    rows = []
    for case in selection["selection"]:
        old, new = reference[case["id"]], fresh[case["id"]]
        control = new["f3b"]
        timings = []
        for trial in control["trials"]:
            row = {k: trial.get(k) for k in ("status", "transitions", "hot_ms", "cpu_ms",
                   "search_rpc_ms", "prediction_prepare_ms", "detail", "replay_ms",
                   "frame_audit_ms", "menu_ms", "peak_working_set_bytes")}
            if row["detail"] is not None:
                row["detail"] = row["detail"].split("; logs=", 1)[0]
            if row["search_rpc_ms"] is not None:
                row["request_residual_ms"] = (row["search_rpc_ms"] - row["prediction_prepare_ms"]
                                              - row["hot_ms"])
            timings.append(row)
        policies = {policy: s2c.row_for(control, new[policy]) for policy in new}
        rows.append(dict(case=case, policies=policies, f3b_attempts=timings,
                         root_preparation_reference=roots[case["id"]]["audit"]["rebuilds"],
                         reference_policies={policy: s2c.row_for(old["f3b"], old[policy]) for policy in old},
                         refinement=new["f4"].get("refinement"),
                         repeat_differences={policy: s2c.diffs(evidence(old[policy]), evidence(new[policy]))
                                             for policy in new}))
        if case["id"] in retry:
            repeated = retry[case["id"]]
            rows[-1]["retry"] = {
                policy: dict(result=s2c.row_for(repeated["f3b"], repeated[policy]),
                             differences=s2c.diffs(evidence(old[policy]), evidence(repeated[policy])))
                for policy in repeated}
    summary = {}
    for split in s2c.SPLITS:
        picked = [row for row in rows if row["case"]["split"] == split]
        summary[split] = {}
        for policy in selection["policies"]:
            values = [row["policies"][policy] for row in picked]
            summary[split][policy] = dict(
                timing={k: distribution(v["timing"][k] for v in values) for k in values[0]["timing"]},
                reference_timing={k: distribution(row["reference_policies"][policy]["timing"][k]
                                                   for row in picked) for k in values[0]["timing"]},
                levels=dict(Counter(v["level"] for v in values)),
                identical=sum(not row["repeat_differences"][policy] for row in picked))
    sessions = bank.read(args.fresh / "sessions.json")
    bank.atomic(args.output, dict(versions=plan["versions"], contract=contract, reference=ref_contract,
                                  sessions=sessions, reference_sessions=bank.read(args.reference / "sessions.json"),
                                  retry_sessions=bank.read(args.retry / "sessions.json") if args.retry else [],
                                  rows=rows, summary=summary))


if __name__ == "__main__":
    main()
