# II-J.4 延迟抽牌 Power 的战斗结束边界

定向候选 `0.51.5-iij.4` 继承 II-J.3。验证使用 II-H.7 战斗宿主、CoreCLR 9.0.7 与 STS2 v0.113.1 Build 26660232。正式全量验收基线为 `0.51.5-iii.8`。

## 首个语义偏离

II-J.3 固定路线复放在 II-E `1:000002` 索引 42 重现唯一原生差异。此前各公开观察没有延迟抽牌 Power。Sovereign Blade 击杀最后一名敌人，战斗进入结束状态。同一次出牌让 Pale Blue Dot 达到计数门槛，Solver 的出牌后补偿添加了两层 `DRAW_CARDS_NEXT_TURN_POWER`。原生 `PowerCmd.Apply` 在创建或叠加前检查 `CombatManager.IsEnding`，因此这个边界没有新 Power。

修复在 `PowerLifecycleSupport.AfterCardPlayed` 的 Pale Blue Dot 应用处对齐原生命令的结束状态检查。保留原触发记账，避免在战斗结束时创建或叠加 Power。Hammer Time 与 Automation 在两端的公开 Power 和完整续体一致，同根对照保留两者。

## 定向验收

- 两个独立原生对照从同一历史阈值状态分叉。致胜 Sovereign Blade 的终局没有新 Power。非致胜 Glimmer 确认后精确创建两层，随后回合准备消费并移除。两条分支的完整续体戳覆盖牌区和 RNG，稳定非终局合法菜单精确匹配。早期尝试的独立短牌组遇到原生卡池和出牌约束，最终对照复用已核实的历史准备前缀。
- 固定路线索引 0–41 的逐步证据保持一致，索引 42 修复后获精确终局戳。43 个动作对应 31 个稳定原生边界。
- 唯一一次同根重采读取原 pair16 采样账本中的根规格、初始快照及行为种子，预算 128，优化关闭。原 43 个决策记录全部一致，得到 `admissible_predicted_win / exact_native_match`，无新增首差。
- II-H.8 Sovereign Blade 历史路线与 Forge 正负例、II-I.1 Hammer Time 普通和升级版及 II-I.8 Plot 均通过。Quasar、CLEANSE、Guards、Hidden Daggers 的原生夹具通过。本轮只做定向验证。

[结构化证据](../experiments/m1-nosl3c-iij4/evidence.json)

## 复现

从仓库根运行，使用新日志前缀。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$r = 'new-iij4'
$s = "logs/$r-solver"
$e = 'experiments/m1-nosl3c-'
$h = "${e}iij4"
python "$h/verify_route.py" "logs/$r-before" logs/iij3-solver
python "$h/build_solver.py" $s
python "$h/verify_route.py" "logs/$r-after" $s
python "$h/verify_power.py" "logs/$r-power" $s
python "$h/resample_hammer.py" "logs/$r-resample" $s
python "${e}iih8/verify_forge.py" "logs/$r-forge" --solver $s
python "${e}iih8/verify_history.py" "logs/$r-blade" --solver $s --ledger logs/nosl3c-iie-broad
python "${e}iii1/verify_hammer.py" "logs/$r-hammer" --solver $s
python "${e}iii8/verify_plot.py" "logs/$r-plot" --solver $s
python "${e}iij1/verify_choices.py" quasar "logs/$r-quasar" $s
python "${e}iij1/verify_choices.py" instances "logs/$r-cleanse" $s
python "${e}iij2/verify_guards.py" "logs/$r-guards" $s
python "${e}iij3/verify_daggers.py" compare "logs/$r-daggers" $s
python "$h/export_evidence.py" "logs/$r-evidence.json" --prefix $r --before "logs/$r-before" --solver $s
```
