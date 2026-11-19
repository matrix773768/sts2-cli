from collections import Counter, defaultdict
from pathlib import Path

from analyze import analyze, read
from design import DOMAIN, generate, stamp

HERE = Path(__file__).resolve().parent


def test_manifest_is_fixed_and_encounters_are_disjoint():
    plan = read(HERE / "manifest.json")
    assert plan["domain"] == DOMAIN
    assert list(generate()) == plan["cases"]
    cases = [x["case"] for x in plan["cases"]]
    assert len({c["spec"]["seed"] for c in cases}) == len(cases) == 96
    assert all(c["split"] == "development" and c["spec_sha256"] == stamp(c["spec"]) for c in cases)
    assert Counter(c["cohort"] for c in cases) == {"train": 48, "selection": 24, "report": 24}
    splits = defaultdict(set)
    for c in cases:
        splits[c["spec"]["encounter"]].add(c["cohort"])
    assert len(splits) == 8 and all(len(group) == 1 for group in splits.values())


def test_qualified_ledger_preserves_fixed_prefixes_and_root_pairs():
    plan = read(HERE / "manifest.json")
    data = read(HERE / "benchmark.json.gz")
    assert data["manifest_sha256"] == stamp(plan)
    rows = [r for batch in data["batches"] for r in batch["rows"]]
    assert len(rows) == 384 and len(data["batches"]) == 12
    assert all(r["evidence"] == "prediction_only" for r in rows)
    keys = {(r["id"], r["defense_first"], r["cap"]): r for r in rows}
    assert len(keys) == len(rows)
    for (id_, policy, cap), row in keys.items():
        if cap == 48 and row["terminal"]["status"] != "build_error":
            longer = keys[id_, policy, 96]
            assert row["trajectory"] == longer["trajectory"][:len(row["trajectory"])]
    for report in analyze(data, plan).values():
        scores = report["all"]["all"]["paired"]
        assert scores["roots"] == 96
        assert scores["hp_distinguishable"] >= scores["survival_distinguishable"]


def test_historical_budget_probe_and_native_evidence_boundaries():
    probe = read(HERE / "probe.json.gz")
    small, large = probe["historical"]
    assert small["terminal"]["status"] == "truncated"
    assert small["terminal"]["feedback"]["combat_terminal"] is None
    assert small["trajectory"] == large["trajectory"][:48]
    assert len(probe["audits"]) == 8
    assert all(row.get("evidence") != "L3" for row in probe["audits"])
