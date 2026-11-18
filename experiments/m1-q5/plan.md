# Q5 candidate rules

Use Q4 Boss route C through step 18. Start each candidate at the same strictly audited parent. End at the next player round, a terminal stamp, the first unsupported boundary, or eight actions, whichever comes first.

| Order | Rule at the first decision | Second decision |
| ---: | --- | --- |
| 1 | Play the first legal FRANTIC_ESCAPE | Frozen Q1 |
| 2 | Frozen Q1, the one-candidate baseline | Frozen Q1 |
| 3 | EndTurn | Frozen Q1 if still active |
| 4 | Play the first legal COMPACT | Frozen Q1 |
| 5 | Play the first legal SKIM | Frozen Q1 |
| 6 | Play the first legal SPINNER | Frozen Q1 |
| 7 | Play the first legal MOMENTUM_STRIKE | First legal FRANTIC_ESCAPE |
| 8 | Play the first legal COMPACT | First legal FRANTIC_ESCAPE |

After the prescribed decisions, apply frozen Q1 to the new observation at each step. If a prescribed card has no legal instance, stop that candidate. The bounded candidate menu contains no potion actions. Pending selection or an unsupported prediction is a stop.

Budgets 2, 4 and 8 use the corresponding ordered prefixes. Exclude death, unresolved boundaries and mid-round caps from selection. Rank the remaining endpoints lexicographically by victory, Sandpit at least two, higher HP, lower enemy HP, then less energy spent on Escape. Break equality by rule order. Compare endpoints and report finite propagation separately from combat outcomes.

Two independent matrices. Rebuild the parent in every native verification process. Verify each distinct completed or action-capped suffix, including death witnesses. Cap native processes at 35 seconds and managed GC heap at 256 MiB. The driver allows a 180-second launch window per matrix. Hidden RNG is used only by offline-oracle execution and evidence.
