# M1-INFRA-1H2

`h-state` is an opt-in complete-turn backend for the frozen INFRA producer. The reference deployment remains corrected 1A (`h-batch`). Use the independent `research/m1-infra` checkout with staged INFRA-1H K6, corrected base2, and the pinned instrumented CombatSolver 1.0.2 assets. The build checks the parent binaries, portable PDB source checksums, adapter sources and Hot solver SHA-256.

## Build and reproduce

Run from the repository root in PowerShell. Give each charged attempt a fresh label. The launcher serializes workers and enforces the independent 7,200-second allocation, including failed attempts.

```powershell
python -B experiments/m1-infra1h2/work.py rebuild-shadow build.py 5d
python -B experiments/m1-infra1h2/work.py rebuild-natural build.py 5d --production
python -B experiments/m1-infra1h2/work.py rebuild-world-probe build.py 5e --production
python -B experiments/m1-infra1h2/work.py replay-native native_h2.py
python -B experiments/m1-infra1h2/work.py replay-panel check.py --full
python -B experiments/m1-infra1h2/work.py compare-planners turns.py
python -B experiments/m1-infra1h2/work.py permute-roots invariance.py
python -B experiments/m1-infra1h2/work.py compare-slug-world slug_check.py --probe
```

The formal producer retains its original dependency identity check. With the frozen shared installation restored, the selectable entry point is

```powershell
python -B experiments/m1-infra1h2/work.py formal-sample ../m1-infra0/run.py h2-formal natural V2 baseline --sample 8 --variant h-state
```

The recorded paired measurements used the separately identified local Workshop runtime in `evidence/runtime.json`. `measure.py` validates both the frozen workspace inputs and that runtime before invoking the existing production worker, then checks each closed record against the archived corrected-1A output. The built host still loads the frozen repository game DLL. The audit mode assigns conditional-world production to corrected 1A.

```powershell
python -B experiments/m1-infra1h2/work.py reproduce-batch measure.py rep-batch natural h-batch
python -B experiments/m1-infra1h2/work.py reproduce-hot measure.py rep-hot natural h-state
python -B experiments/m1-infra1h2/work.py reproduce-all measure.py rep-all natural h-state full
python -B experiments/m1-infra1h2/summary.py
python -B experiments/m1-infra1h2/verify.py
```

## Implementation boundaries

| Entry | Responsibility |
| --- | --- |
| `Branch.cs`, `lane.py` | Import a public opening, allocate stable handles, enumerate bound cards and targets, advance Hot values with Cold sidecars, resolve public draws and player selections from the nearest stable parent, and publish B, pre-draw C or terminal resources. |
| `tactics.py`, `production.py` | Reproduce the frozen reduced graph for the qualified deterministic card roles, settle its successors, use the frozen singleton G2 and conditional search, and discard the entire candidate on an unsupported boundary. |
| `Slugs.cs`, `slugs.py`, `slug_check.py` | Import the turn-two public Corpse Slugs history and validate independent continuations on 5E audit root 123. This is a separate experimental lane. |
| `private_fix.py`, `native_h2.py` | Extend the private K6 verifier with generated and modified bindings, accumulate nested selections, check the OUTRAGE discard copy and adjudicate the first disagreements in the native game. |
| `evidence/` | Machine-readable stage A–D comparisons, runtime identities, closed-record fingerprints, per-turn fallbacks and worker ledger. |

`open` and `open_slugs` start a handle generation. `advance` keeps the parent valid for sibling forks. `release` invalidates one handle and its transcript cache. `clear` releases the generation. Handles increase monotonically. Public branches use HotDraw event guards and a zero-initialized RNG. The private verifier executes with the actual RNG. The production worker continues to commit real environment actions through the original host.

See [the research report](../../docs/m1-infra1h2-hot-state-search.md) for measured coverage and remaining work.
