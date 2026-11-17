# CLAUDE.md

## Testing Requirements

### During development

Identify the affected behavior and risk before editing. After a small change, run only directly relevant tests. Choose the smallest sufficient set and avoid running successively broader sets by default. Stop after the required checks pass. Reuse prior results for unaffected behavior and identify the revision tested.

| Risk | Validation |
| --- | --- |
| Low | Directly relevant unit or targeted tests. Documentation-only changes normally need only a diff check. |
| Medium | Relevant targeted tests and representative real-engine cases where needed. |
| High | Add focused real-engine regression for affected invariants. RNG, Save/Load, game-state transitions, native async behavior, and cross-process determinism warrant additional coverage when affected. |

For a new failure, inspect the diff and existing logs, then run the smallest reproduction. Expand coverage only when the cause is unclear, shared state is involved, or the suspected impact increases. Verify the original failing case after repair. Preserve existing assertions, seeds, and coverage unless explicitly changing a test fixture for a verified reason. Report unresolved native behavior or major architectural disagreements before continuing the affected work.

### Stage and commit acceptance

Run the module's targeted suite once at module completion, reusing the result if the relevant code and fixtures have not changed. Run full pytest once by default at the end of a major milestone. Run the five-character batch when changes affect native combat, game flow, or other behavior with global simulation impact. Documentation and fixture-only changes normally do not require it.

Review the diff and run `git diff --check`. Report actual checks and results, skipped full validation, and remaining risks. Cite versioned prior runs when relevant and identify them as prior results. Before running experiments materially beyond the task's test budget, explain what uncovered failure they could detect.

### Performance experiments

Manage benchmarks separately from regression tests. Use a small sample to validate measurement and statistics during development. Collect formal benchmark data after the feature stabilizes. Report sample counts and note when P95 or other tail estimates are unstable.

### Full compatibility acceptance

Run the full pytest suite and five full games per character on the supported game and runtime configuration documented in `docs/PROJECT_STATUS.md`. Full compatibility requires the suite to pass and Ironclad, Silent, Defect, Regent, and Necrobinder each to complete 5/5 games without a crash or stall. Report skips and their reasons. Never report a check as passed if it was not run. Development verification and commit acceptance may have a narrower scope.

## Localization

- Always use the game's official Chinese translations (from `localization_zhs/`)
- Never invent translations — look them up
- All user-facing strings must go through `t(en, zh)` for bilingual support
- Template variables like `{Damage}`, `{Block}`, `{MaxHp}` must be resolved to actual values before display

## Build

```bash
~/.dotnet-arm64/dotnet build src/Sts2Headless/Sts2Headless.csproj
```

## Key Architecture

- `src/Sts2Headless/RunSimulator.cs` — game lifecycle, decision point detection, state serialization
- `src/Sts2Headless/Program.cs` — JSON command router
- `src/GodotStubs/` — replacement GodotSharp.dll (no-op Godot types)
- `python/play.py` — interactive terminal player
- `python/play_full_run.py` — batch testing tool
- `lib/` — game DLLs (not in repo, copied by setup.sh)
- `localization_eng/`, `localization_zhs/` — bilingual loc data

## Conventions

- **Event completion**: trust `localEvent.IsFinished`. Never gate on "option count unchanged after a choice" — events legitimately loop on the same page (Slippery Bridge Hold On) and post-selection continuations (heal/enchant/add-card) often run on the same options page; force-finishing kills them silently.
- **Async selection continuations**: any path whose effect can open a card_select / card_reward / bundle (event option, shop relic pickup, etc.) must run on `Task.Run(...)` and yield as soon as `_cardSelector.HasPending` / `HasPendingReward` / `_pendingBundles != null` appears. The Task completes naturally once the external `select_cards` feeds the selector's TCS. Reference shape: `DoChooseOption`, `DoBuyRelic`.
- **DynamicVar preview during serialization**: `UpdateDynamicVarPreview` mutates the live card. Bracket reads with `ClearPreview` **before and after** — leaving the card in preview state corrupts subsequent play actions (Momentum Strike `PlayCardAction` failure).

## Protocol notes

- `card_select` decision uses key `cards` (not `options`) and action `select_cards` with comma-separated `indices`.
- `AnyEnemy` cards/potions require `target_index` when ≥2 enemies are alive; with a single alive enemy the adapter auto-targets.
