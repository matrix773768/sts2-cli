"""Check frozen development coverage and independent witness accounting."""
from pathlib import Path

from summarize import read

HERE = Path(__file__).resolve().parent


def test_development_completion_preserves_plan_and_failures():
    old = read(HERE.parent / "m1-s3a/hard.json.gz")["rows"]
    new = read(HERE / "development.json.gz")["rows"]
    inputs = read(HERE / "development-72.json")
    assert [r["input"] for r in new] == inputs["cases"]
    assert set(r["input"]["replicate"] for r in new) == {1, 2, 3}
    assert len({r["input"]["id"] for r in old + new}) == 96
    assert all(r["input"]["split"] == "development" and r["cap"] == 512
               and "root_sha256" in r and r["loaded_solver"]["sha256"] == r["solver_sha256"]
               for r in old + new)
    for current, following in zip(new[:-1], new[1:], strict=True):
        if current.get("discard_reason"):
            assert current["discard_exit_code"] != 0 and following["started_cold"]
            assert following["pid"] != current["pid"]


def test_only_same_root_witnesses_resolve_search_coverage():
    data = read(HERE / "diagnostic.json.gz")
    assert len(data["rows"]) == 11
    assert sum(r["diagnosis"] == "predicted_witness" for r in data["rows"]) == 3
    for row in data["rows"]:
        assert all(r["root_sha256"] == row["root_sha256"] for r in row["runs"])
        assert ("c_extended" in {r["method"] for r in row["runs"]}) == (row["group"] == "capped")
        assert (row["diagnosis"] == "solvability_unknown") == all("winner" not in r for r in row["runs"])
    assert [r["status"] for r in data["native_audits"]] == ["win", "strict_difference", "win"]
    assert all(row["input"]["id"] != row["input"]["source_case"]
               and row["input"]["spec"]["hp"] == row["old_hp"] + 20 for row in data["perturbations"])


def test_failed_focus_never_matches_the_witness_prefix():
    trace = read(HERE / "trace.json.gz")["trace"]["result"]
    evidence = read(HERE / "diagnostic.json.gz")
    row = next(r for r in evidence["rows"] if r["id"] == "f2f29fd990637955")
    route = next(r["winner"] for r in row["runs"] if "winner" in r)
    def action_key(action):
        return action.get("card_id"), action.get("target_combat_id")

    prefix = [action_key(a) for a in route["actions"][:5]]
    attempted = [[action_key(trace["history"][i]["action"]) for i in route["nodes"][1:]]
                 for route in trace["routes"]]
    assert sum(path[:4] == prefix[:4] for path in attempted) == 33
    assert not any(path[:5] == prefix for path in attempted)
