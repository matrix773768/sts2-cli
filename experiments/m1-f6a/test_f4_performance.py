"""Verify the recorded equivalence, profiling coverage and budget accounting."""
from pathlib import Path

from summarize import read

HERE = Path(__file__).resolve().parent


def test_abba_preserves_frozen_results_and_budget():
    data = read(HERE / "paired.json.gz")
    assert [c["lean"] for c in data["cohorts"]] == [False, True, True, False]
    expected = {}
    for cohort in data["cohorts"]:
        rows = cohort["rows"]
        assert not cohort["profile"] and len(rows) == cohort["planned"] == 12
        assert len({r["pid"] for r in rows}) == 1
        for row in rows:
            assert row["matched_b1b"] and not row.get("discard_reason")
            assert row["runtime"]["lean"] == cohort["lean"]
            assert row["first"]["transitions"] + row["quality"]["transitions"] <= 512
            signature = (row["semantic_sha256"], row["rng_sha256"], row["risks"])
            assert expected.setdefault(row["input"]["id"], signature) == signature


def test_phase_counts_account_for_replay_and_rolling_candidates():
    for cohort in read(HERE / "profile.json.gz")["cohorts"]:
        assert len(cohort["rows"]) == 12
        for row in cohort["rows"]:
            scopes = row["profile"]["adapter"]
            assert scopes["seed"]["count"] == 1
            assert scopes["anchor_layout"]["count"] == 1
            assert scopes["replacement"]["count"] == scopes["candidate_attempt"]["count"]
            assert scopes["rollout"]["count"] == len(row["quality"]["attempts"])
            assert scopes["replay"]["count"] == row["quality"]["transitions"]
            assert row["profile"]["forks"] == scopes["replay"]["count"]
            assert row["wire"]["chars"] > 0
