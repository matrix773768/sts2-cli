# II-K.2.2 — Lightning Rod 终局层数

起点为 `port/v0.113.1@35a99ef5dae8fbd58099709348cba447e287cf52`。核验 `0.51.5-iik.2.1` 的本地 Solver DLL SHA-256 与构建清单一致。候选 `0.51.5-iik.2.2` 继承此前累计修复，Solver DLL SHA-256 为 `47e33c172d8a8da5a8a179ce35ceb396dd1cad930999bc34f8fe2f13e53fa759`，实测与清单一致。复用 II-H.7 战斗宿主与 CoreCLR 9.0.7。正式全量验收基线为 `0.51.5-iij.4`。

## 原生顺序与修复

holdout `1:000020` 的索引 17 为 `end_turn`。当时最后一只 Exoskeleton 剩 4 HP。玩家回合结束后战斗继续，随后在下一玩家回合的能量重置钩子中，Lightning Rod 的入列使满槽队列挤出一个闪电球并击杀末敌。原生等待入列及挤出结算，再调用 `PowerCmd.Decrement`。此时战斗已处于 `IsEnding`，即使正式胜利尚待检查锁定，`PowerCmd.ModifyAmount` 仍直接返回。原生最后进入 `card_reward`，Lightning Rod 保持 2 层。该顺序可核对本地 `logs/iik22-native-order.il`，其中 `AfterEnergyReset` 在 `0040` 调用入列、`009b` 调用减层，`ModifyAmount` 在 `002e` 读取 `IsEnding`。

Solver 的 Lightning Rod 镜像在球体结算后直接写层数，导致终局剩 1 层。修复仅在 `HandleLightningRodPower` 的减层处增加 `IsEnding` 检查。入列、选择挂起、通用终局调度及严格认证合同均沿用原实现。

## 定向验收

| 检查 | 结果 | 耗时 |
| --- | --- | ---: |
| iik.2.1 冻结复放 | 索引 17 复现首差，原生 2 层、预测 1 层 | 6.2 秒 |
| 非致胜原生夹具 | 三张 Zap+ 填满队列，Lightning Rod+ 提供 2 层。满槽触发后战斗继续，原生、基线和候选均降至 1 层，续体戳精确 | 基线 3.9 秒，候选 4.7 秒 |
| 致胜原生夹具 | 同一精简牌组，末敌剩 10 HP 时打出 Lightning Rod+ 并结束回合。三枚闪电球被动共造成 9 点伤害，下一回合 Lightning Rod 触发挤出致胜。原生保留 2 层，基线降至 1 层，候选终局戳精确 | 基线 5.2 秒，候选 5.5 秒 |
| 候选冻结复放 | 18 个决策及 18 个稳定原生边界均精确，索引 17 获胜 | 5.7 秒 |
| 唯一一次同根重采 | 原模型、行为种子 `11842007917732921747`、预算 128，关闭优化。保留全部 18 个历史决策记录，取得 `admissible_predicted_win / exact_native_match`，终局戳与冻结复放一致 | 根内 8.7 秒，命令墙钟 17.9 秒 |

候选编译一次，编译器计时 40.50 秒，出现一条 CS9124 警告。终局戳为 `a1f61b184b3d2ea19b071ea1639adf95786cbf11d96ea7e9513b5292543494dd`。本轮改动仅作用于 Lightning Rod 的减层，Glass Orb 和敌方 Strength 沿用 II-K.2.1 的独立首差记录。

## 复现

在仓库根使用新的输出前缀。冻结复放与重采均从 II-J.5B 原 holdout 账本只读提取指定根。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$h = 'experiments/m1-nosl3c-iik22'
$r = 'logs/new-iik22'
python "$h/verify_route.py" "$r-before" logs/iik21-solver
python "$h/verify_rod.py" "$r-fixture-before" logs/iik21-solver
python "$h/build_solver.py" "$r-solver"
python "$h/verify_rod.py" "$r-fixture-after" "$r-solver"
python "$h/verify_route.py" "$r-after" "$r-solver"
python "$h/resample_rod.py" "$r-resample" "$r-solver"
```
