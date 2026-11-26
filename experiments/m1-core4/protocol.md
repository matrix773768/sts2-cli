Use CORE-3 training/development families and four new independently seeded G2 fights per training family. The final paired panel takes all open DC1 development families outside CORE-0, then fills to 100 from CORE-3 held-out families after its 12 deployment cases. Use fresh seeds and compare G2, G2-search (24), CORE-3 simple full search, semantic search V0 and updated V1. All arms use identical natural starts per family. Check policies before opening confirmation. Train the first semantic model on G2; collect full on-policy outcomes for V0 across training families, then update the value under that continuation. Include G2 as a within-turn public reference. Use root-relative signed loss plus paid HP cost back to the combat opening. Report family-paired utility intervals and win/death rates. Promote only on positive lower 95% paired utility bound against G2 with no drop in wins. Caps and errors remain unlabelled. No retuning on confirmation.

## Record contract

Each gzip JSONL row is one complete combat attempt. Use the family key for splitting and clustered uncertainty. The seed is a replay key for the host and offline pairing only. An independent world within the same family gives another conditional outcome. The model receives only public C tensors. The full CORE-2 snapshot and its static rule reference remain available to other encoders.

| Files in evidence | Continuation and use |
| --- | --- |
| nat0..5.gz | Four new G2 seeds per training family. Training split is implicit. Join by family to the public specifications in panels.json.gz. |
| on0..5.gz, val.gz | V0 under continuous intervention. Train and development are explicit. Paired rows revert one midgame turn to G2 then return to V0. |
| test-ARM-SHARD.gz | Primary independent combat panel, one fixed fresh seed per family. |
| rep-REPEAT-ARM.gz | Three additional fresh seeds run after primary evaluation with policies frozen. |
| paired-check.gz | An additional midgame skip under frozen V0 for eligible primary test families. For diagnosis only. |
| transfer-ENCOUNTER-ARM.gz | Constructed transfer fights. Keep the held-out build and replay a complete, legal encounter with the donor's act and variant. |

For supervised distribution training accept a resolved recorded terminal only. Label every captured C in that fight by death or signed HP loss from C to terminal. The winner's HP may increase. Gold, maximum HP and potion slots are preserved in terminal payloads. Duration-weighted C prediction metrics and family-weighted policy metrics have different denominators. The training scripts read only explicitly supplied paths and accepted splits. V1 likelihood uses only V0-continuation rows. The paired regression compares the two first distinct post-intervention C outcomes under the same frozen suffix. Truncated rows and pairs missing a required C have no such label.

## Replay

From the repository root, run `python experiments/m1-core4/reproduce.py logs/new-core4` with a new directory. This uses Python, NumPy, CPU PyTorch, the CORE-2 host at `logs/core2-state03`, the local STS2 runtime and the frozen G2 runtime resolved by CORE-3. It reuses the committed panel and CORE-3 G2 fight shards. The normal workflow requires no internet access. Standalone encoding and model tests read the committed evidence. Run `python -m unittest discover -s experiments/m1-core4`. Model inputs are numeric global features, padded event tensors and a validity mask returned by `semantic.pack`. Use `Value.eval()`, softmax, and the DC2B opening-relative expectation in `improve.graph_plan`.

The single-seed primary decision rule above was fixed before deployment. Subsequent seed replication, skipped-turn diagnostics and unseen-species transfer are reported separately. No confirmation observation entered a gradient update or candidate-selection threshold.
