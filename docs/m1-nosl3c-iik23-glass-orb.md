# II-K.2.3 — Glass Orb 终局衰减

起点为 `port/v0.113.1@a31b27b74ec47c736d9116e14d9dc6a10f687cc4`。基线 `0.51.5-iik.2.2` 与候选 `0.51.5-iik.2.3` 的本地 DLL 均已核对构建清单。候选继承 II-K.2.2，SHA-256 为 `9623cf60996481076faf6a1ac11ff7688512dc9402dd586442b39a738e0f3d51`。复用 II-H.7 战斗宿主与 CoreCLR 9.0.7。正式全量验收基线为 `0.51.5-iij.4`。

## 原生顺序与根因

原生 `OrbQueue.BeforeTurnEnd` 拍摄队列快照，按顺序等待每枚球的回合结束回调。Glass Orb 经 `TriggerPassive` 进入 `Passive`，取得可命中目标列表和当前被动值。正值先将球的基础数值减一并限制为非负，再用衰减前的被动值对所取目标结算伤害。致胜后后续 Glass Orb 仍衰减，空目标列表使伤害为空操作。玩家回合结束第一阶段在球体回调完成后检查并锁定胜利。原生程序集调用摘录保存在本地 `logs/iik23-native.il`。

holdout `1:000021` 索引 20 的末两只 Nibbit 均剩 3 HP。被动值 1 和 2 的球先后造成伤害，第二次伤害击杀两敌。原生继续将末两枚球从 3、4 衰减到 2、3。Solver 球体队列继续遍历，但共用的 `OrbPassive` 入口见 `IsEnding` 就提前返回，致使最后两枚球保持原值。

修复仅允许 Glass Orb 的被动在胜负尚未锁定的结束窗口执行，复用既有被动值计算、衰减和伤害逻辑。锁定终局与挂起选择仍在入口阻断，其他球的结束门槛、队列遍历、正式胜负检查及严格认证合同沿用原实现。

## 定向验收

| 检查 | 结果 | 耗时 |
| --- | --- | ---: |
| iik.2.2 冻结复放 | 索引 20 复现原差异，原生 `0,0,1,2,3`，预测 `0,0,1,3,4` | 5.3 秒 |
| 原生夹具 | 三张 Glasswork 与两张 Defend。两个非致胜回合的边界两版均精确；致胜回合末敌剩 6 HP，前两枚球各造成 3 点伤害。终局原生与候选为 `2,2,2`，基线为 `2,2,3` | 基线 4.7 秒，候选 5.2 秒 |
| 候选冻结复放 | 21 个决策及 21 个稳定原生边界均精确，索引 20 获胜 | 5.6 秒 |
| 唯一一次同根重采 | 原模型、行为种子 `10119239168727054556`、128 动作预算，关闭优化。全部 21 个历史决策记录一致，取得 `admissible_predicted_win / exact_native_match`，终局戳与冻结复放一致 | 根内 9.1 秒，命令墙钟 17.5 秒 |
| II-K.2.1／II-K.2.2 局部回归 | 闪电球首阶段锁胜夹具精确。Lightning Rod 致胜保留 2 层、非致胜降至 1 层，两条续体戳精确 | 锁胜夹具 5.4 秒，Lightning Rod 非致胜／致胜 5.0／5.0 秒 |

候选编译一次，编译器计时 62.68 秒，出现一条 CS9124 警告。冻结终局戳为 `6bab4974fa33b23b7d8441f9b70d7fe94ce991868142e960b76734fcec37878e`。敌方 Strength 见证为无球体的 Necrobinder 路线，沿用历史首差记录。

## 复现

从仓库根运行，使用新的输出前缀。冻结复放和重采均从 II-J.5B 原 holdout 账本只读提取指定根。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$h = 'experiments/m1-nosl3c-iik23'
$r = 'logs/new-iik23'
python "$h/verify_route.py" "$r-before" logs/iik22-solver
python "$h/verify_glass.py" "$r-fixture-before" logs/iik22-solver
python "$h/build_solver.py" "$r-solver"
python "$h/verify_glass.py" "$r-fixture-after" "$r-solver"
python "$h/verify_route.py" "$r-after" "$r-solver"
python experiments/m1-nosl3c-iik21/verify_orbs.py "$r-orb-terminal" "$r-solver"
python experiments/m1-nosl3c-iik22/verify_rod.py "$r-rod" "$r-solver"
python "$h/resample_glass.py" "$r-resample" "$r-solver"
```
