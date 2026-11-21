"""Export the II-J.1 independent fixtures and one-root resampling evidence."""
import argparse
import json
from pathlib import Path

from verify_choices import LOGS, batch, save_json


def read(path):
    return json.loads(path.read_bytes())


def sample(folder):
    item = batch(folder, 0, "000000")
    row, = item["rows"]
    audit = read(LOGS / folder / "audit/000000-000000.json")
    actions = []
    for t in row["transitions"]:
        action, obs = t["action"], t["observation"]
        card = action["card"]
        choice = action["choice"]
        actions.append(dict(kind=action["kind"],
                            card=obs["hand"][card]["id"] if card is not None else None,
                            candidate=obs["decision"]["candidates"][choice]["id"] if choice is not None else None,
                            advanced=t["advanced"]))
    return dict(spec=item["spec"], behavior=row["behavior"], feedback=row["feedback"],
                actions=actions, audit=audit, report=read(LOGS / folder / "report.json"))


def main(out, prefix, solver):
    build = read(solver / "build.json")
    fixtures = read(LOGS / f"{prefix}-quasar-proof/quasar.json")
    instances = read(LOGS / f"{prefix}-instances/draw-instances.json")
    glimpse = read(LOGS / f"{prefix}-glimpse/glimpse.json")
    prior_glimpse = read(LOGS / "iii8-glimpse/glimpse.json")
    before = read(LOGS / f"{prefix}-related-base/related.json")
    after = read(LOGS / f"{prefix}-related/related.json")
    previous = sample("iii9a-sample-8")
    result = sample(f"{prefix}-resample")
    engine = fixtures["engine"]
    assert engine["solver_sha256"] == build["patched_sha256"]
    assert engine["headless_sha256"] == "b3f8ce1d862bdb98000bfeb90d701239e50be17034739c5c2ed18e26716150f0"
    assert engine["game"] == "0.113.1/26660232" and engine["coreclr"] == "9.0.7"
    assert all(engine == e for e in (instances["engine"], glimpse["engine"], after["engine"],
                                     result["audit"]["versions"]))
    assert len(fixtures["cases"]) == 3 and all(
        c["status"] == "active" and c.get("stamp") for c in fixtures["cases"])
    assert instances["exact_matches"] == 2
    assert glimpse["cases"] == prior_glimpse["cases"]
    assert previous["spec"] == result["spec"] and previous["behavior"] == result["behavior"]
    assert previous["actions"][:4] == result["actions"][:4]
    assert not previous["actions"][4]["advanced"] and result["actions"][4]["advanced"]
    assert result["audit"]["certification"] == "exact_native_match" and result["audit"]["terminal_verified"]
    assert result["report"]["attempted"] == 1 and result["report"]["optimizer"] == {}
    save_json(out, dict(build=build, engine=engine, quasar=fixtures["cases"],
                        cleanse_instances=instances, glimpse=glimpse["cases"],
                        related_before=before, related_after=after,
                        resample_before=previous, resample_after=result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--prefix", default="iij1")
    parser.add_argument("--solver", type=Path, default=LOGS / "m1-nosl3c-iij1-candidate")
    args = parser.parse_args()
    main(args.output, args.prefix, args.solver)
