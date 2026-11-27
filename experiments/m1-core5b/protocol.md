# CORE-5B protocol

Freeze before opening new results. Use all 288 CORE-5A worlds as regression, 40 hash-selected distinct 80-max-HP families with an original/V1/V2 joint loss for full-information F3B and independent native replay. Set HP and max HP to 999 on 24 of those roots and 24 distinct 80-max-HP non-joint-loss families. Keep the seed, encounter, upgrades and resources. Compare the three frozen baselines G2, G2-search and 5A V2, plus recovered and high-budget V2.

Fresh confirmation uses 48 independently generated 80-max-HP deck families, two shared seeds each, excluding all DC1 and CORE-5A compositions. Compare original 5A V2 (128 transitions / 32 settlements / 48 reference requests), reference repair only (128/32/48), medium (256/48/96), high (512/80/192), and repaired V1 at high budget. Settlement expansions per path 8, 8, 12, 20, 20 respectively. Full mass and +1 gate throughout. Primary contrasts are paired utility and win rates with family-clustered 95% bootstrap intervals. Teacher recommendation requires positive lower utility bound high vs repaired base with no win reduction. Select human reviews after evaluation for diagnosis. Full RNG is only available to Oracle validation and actual combat execution.

## Reproducing the study

Use the installed game and the pinned CORE-5A and SV4A hosts. Build the new host once with `python experiments/m1-core5b/build5b.py logs/core5b-host`. From the repository root, set `$env:STS2_CORE5B_RUN` to a new directory. This keeps new evidence and engine logs separate from the submitted runs. Execute the following scripts in `experiments/m1-core5b` with the same Python environment.

1. Run `panel.py`, then `study.py`. The latter resumes completed shards. The historical reference-only 768 arm is an additional diagnostic specified after the primary confirmation.
2. Run `oracle.py`, `beam.py`, `audit5b.py`, `counterfactual.py`, and `metrics5b.py`. Oracle witnesses include privately initialized route checks. The NOSL actors never load these records.
3. Run `review.py`, then `long_turns.py`, `fifth.py`, `candidate_audit.py`, and `pending_review.py`. Run `hp_replay.py` before `hp_native.py`. Use `cost_breakdown.py` for common natural roots, and `render_review.py` for the Chinese review.

The archived experiment uses independently timed jobs. The ledger records their elapsed seconds and the separate estimate for unmetered diagnostics. An original run can be audited directly from the submitted files with the environment variable unset.
