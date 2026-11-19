"""Run the prior truncated root and independent native cohort sentinels."""
import argparse
import gzip
import json
from pathlib import Path

from run_cohort import base, execute, BudgetEpisode, interaction, stamp, verify_budgets
from native_interaction import audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    versions = base.s3a.solver_binding(output, base.s3a.FIXED, base.ROOT / "logs/m1-e3f/release")
    data = base.bank.read(args.benchmark)
    manifest = base.bank.read(Path(__file__).with_name("manifest.json"))
    base.Episode, base.choose = BudgetEpisode, interaction.choose
    lifecycle = []
    item = next(item for item in base.cases() if item["case"].get("rule") == "dexterity")
    with base.worker(output, item, versions, lifecycle) as (game, _):
        original = [execute(game, item, True, cap, "historical_control") for cap in (48, 96)]
    verify_budgets(original)
    with gzip.open(Path(__file__).resolve().parents[1] / "m1-n2a1/benchmark.json.gz", "rt", encoding="utf-8") as stream:
        old = json.load(stream)
    archived = next(r for r in old["rows"] if r["id"] == item["case"]["id"] and r["defense_first"])
    assert archived["terminal"]["status"] == "truncated"
    assert stamp(original[0]["trajectory"]) == stamp(archived["trajectory"])
    assert original[0]["terminal"]["audit_stamps"] == archived["terminal"]["audit_stamps"]

    primary = [r for batch in data["batches"] for r in batch["rows"]]
    roots = {r["id"]: r for batch in data["batches"] for r in batch["roots"]}
    result = dict(versions=versions, historical=original, historical_lifecycle=lifecycle, audits=[])
    for group in range(8):
        # Alternate roles, take the predesignated mid-HP recipe and non-defense strategy.
        sentinel = manifest["cases"][12 * group + (1 if group % 2 == 0 else 7)]
        id_ = sentinel["case"]["id"]
        root = roots[id_]
        row = next(r for r in primary if r["id"] == id_ and r["cap"] == 96 and not r["defense_first"])
        started = base.perf_counter()
        lifecycle = []
        if root["status"] != "native_built" or "audit_actions" not in row["terminal"]:
            check = dict(status="not_auditable", detail=row["terminal"])
        else:
            with base.worker(output, sentinel | {"root_sha256": root["root_sha256"]}, versions,
                             lifecycle) as (game, surfaces):
                check = audit(game, surfaces["public_root"], row)
        result["audits"].append(dict(id=id_, elapsed_ms=base.ms(started), lifecycle=lifecycle, **check))
        base.bank.atomic(output / "probe.json", result)


if __name__ == "__main__":
    main()
