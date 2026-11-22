# II-K.2.4 — Fossil Stalker 致死边界 Strength

起点为 `port/v0.113.1@9f40a493f9acfacb84fe4c40f1dfb447a8c13e88`。基线 `0.51.5-iik.2.3` 和候选 `0.51.5-iik.2.4` 的 DLL 均已核对构建清单。候选继承此前累计修复，SHA-256 为 `bc2232abb4b271fe6299e0e6b9332033dff736ed26aeefb74491bf123067a683`。复用 II-H.7 战斗宿主和 CoreCLR 9.0.7。正式全量验收基线为 `0.51.5-iij.4`。

## 原生顺序与根因

holdout `0:000023` 索引 9 结束回合时，玩家 13 HP、无格挡且奥斯蒂已死亡。Fossil Stalker 39 HP，攻击意图为 24 点伤害，已有 15 层 Strength 和 3 层 Suck Power。

原生 `AttackCommand.Execute` 等待伤害和死亡处理，再写入攻击历史并调用 `Hook.AfterAttack`。致死处理调用 `LoseCombat` 设置 `PendingLoss`，使 `IsEnding` 在正式进入 `game_over` 前成立。攻击后的 Suck 回调仍按伤害结果统计有效命中，并尝试调用 `PowerCmd.Apply<StrengthPower>`。该命令在查找叠层实例前检查 `IsEnding`，所以原生保留 15 层。Solver 的 Suck 镜像直接通过预测状态写入 Strength，导致终局增加到 18 层。

修复仅在 Suck 镜像尝试应用 Strength 处检查 `IsEnding`。命中统计、攻击回调、公共 Power 写入、终局调度和严格认证合同沿用原实现。原生调用摘录保存在本地 `logs/iik24-native-attack.il`、`logs/iik24-native-loss.il` 和 `logs/iik24-native.il`。

## 定向验收

| 检查 | 结果 | 耗时 |
| --- | --- | ---: |
| iik.2.3 冻结复放 | 索引 9 复现原生 15 层与预测 18 层的首差 | 5.2 秒 |
| 非致死原生夹具 | 同一 Fossil Stalker 的首击为 12 点，玩家初始 66 HP。原生、基线和候选均从 0 增至 3 层 Strength，续体戳精确 | 基线 3.3 秒，候选 4.7 秒 |
| 致死原生夹具 | 相同首击，玩家初始 1 HP。原生与候选进入败局且无 Strength，基线错误施加 3 层。候选终局戳精确 | 基线 3.4 秒，候选 4.7 秒 |
| 候选冻结复放 | 10 个决策及 10 个稳定原生边界全部精确，索引 9 为败局 | 5.3 秒 |
| 唯一一次同根重采 | 原模型、行为种子 `8587029015246351769`、128 动作预算，关闭优化。全部 10 个历史决策记录一致，取得 `admissible_death / exact_native_match`。终局戳与冻结复放一致 | 根内 7.7 秒，命令墙钟 16.6 秒 |

候选编译一次，编译器计时 40.10 秒，出现一条 CS9124 警告。终局戳为 `84b855d04bf52d4689ddfe7e53e03295dbcfbebce9952a0b37ad442eb8df2d33`。测试覆盖 Suck 的致死与非致死分支。

II-K.2 的五条终局差异见证均已定向处理。最终累计验收待完成。

## 复现

从仓库根使用新输出前缀。冻结复放与重采从 II-J.5B 原 holdout 账本只读提取指定根。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$h = 'experiments/m1-nosl3c-iik24'
$r = 'logs/new-iik24'
python "$h/verify_route.py" "$r-before" logs/iik23-solver
python "$h/verify_suck.py" "$r-fixture-before" logs/iik23-solver
python "$h/build_solver.py" "$r-solver"
python "$h/verify_suck.py" "$r-fixture-after" "$r-solver"
python "$h/verify_route.py" "$r-after" "$r-solver"
python "$h/resample_fossil.py" "$r-resample" "$r-solver"
```
