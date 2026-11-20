# M1-NOSL3C-II-D 目标系统与原生差分

基线 `6a441a9`。游戏 0.113.1／Build 26660232，CoreCLR 9.0.7，Solver 0.51.5-iid.1。隔离构建以冻结源码和 II-B 构建步骤为基础，新增队伍能量镜像。训练损失、策略结构和严格准入判据沿用 II-C。

## 目标菜单

动作携带本步的目标类型、阵营及阵营内槽位。显式目标使用当前存活实体公布的槽位。单敌选取继续要求预测可命中。手动友方选取区分出牌者和同队玩家，使用 Solver 对 AnyAlly／AnyPlayer 的玩家范围。全体、随机和自定效果保留唯一动作，由引擎执行。原生目标按其 `CanPlayTargeting` 谓词独立枚举。游戏建根为单玩家，目前不能证明多人友方选择或 Osty 上的所有效果均正确。

玩家与友方实体独立于敌方槽位发布。原有 v3 Actor 通过共享实体编码映射显式友方引用，网络维数保持原样。无显式友方选择时保留旧模型输入。CombatId 仅由审计 RPC 取得，在采样结束后用于两端现时名单的匹配。原生复放通过映射后的当前槽位提交目标。这个映射也用于比较目标血量、格挡和合法菜单，避免同名或召唤后的列表顺序影响核验。

## 原生差分定位

审计在完整续体摘要首次不等时取得预测及原生字段差异。保存最后一致位置、当前动作、卡牌、目标类型及选择效果。原始严格准入规则继续要求完整摘要和锁定终局相同。

敌方阶段死亡见证的首次摘要差异仍在结束回合的第 17 号动作。此前 17 个稳定边界一致。末帧唯一差异为 `Y`，原生 `0/0/0/0`、预测 `0/0/1/1`。另有敌方死亡样本的 `AttackStarts` 与 `Y` 同时不同。字段模式与 E3 当前侧／玩家侧计数口径一致。原生死亡仍无锁定回调，且这项静态对账未逐段验证致死监听器顺序。没有引入终局字段豁免。

## 复现

从仓库根执行，指定已构建的 II-B 锁定 Solver。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$solver = 'logs/m1-nosl3c-iid-solver'
$iid = 'experiments/m1-nosl3c-iid'
python "$iid/build_host.py"
python "$iid/build_solver.py" $solver
python "$iid/probe_targets.py" logs/iid-target-probe --solver $solver
python "$iid/run.py" logs/iid-frozen --solver $solver --config experiments/m1-nosl3c-iic/random-audit.json
python "$iid/run.py" logs/iid-independent --solver $solver --config "$iid/independent.json"
python "$iid/replay_frozen.py" logs/iid-frozen-routes logs/nosl3c-iic-random-final --solver $solver
```

旧动作复放需已有 II-C 审计账本。生成命令见 [II-C 训练准入报告](m1-nosl3c-training-admission.md)。复放在原来存在动作的前缀按动作身份重绑，并检查公共状态。此前没有菜单的根只参加固定种子重新采样。


## 固定路线与随机复测

II-C 的四条早期差异原位置为 8、24、6、13。其中三条的共同原因是召唤后预测与原生的目标槽位顺序不同。改用私有身份重绑后，000008 与 000019 首次差异分别后移至位置 23 和 31 的死亡边界，000018 原动作路线严格准入。000013 仍在位置 24 的自动打牌后出现 Power 差异，预测额外保留 `FREE_ATTACK_POWER`。另一路死亡末帧的原生名单已移除毒气炸弹，预测仍保留对应实体和 Power。尚未确定清理顺序或通用自动出牌消费规则，严格失格。

单玩家对照中，慷慨捐助在两端都没有合法友方候选。全队能量镜像由全队效果调用，能量涌动保持一个隐式动作，能量由 3 至 4 且原生完整续体一致。冻结随机样本中一条完整准入路线实际执行了该效果。

固定种子 4301 的 20 个规格逐项等于 II-C。若原策略存在动作则另行复放记录，重新采样统计单独计算。7 条旧友方类型拒绝均消失。20 根严格归类为 4 准入胜利、8 原生差异、4 E3 风险和 4 unsupported。独立种子 57931 的 30 根全部建成，得到 9 准入胜利、13 原生差异、6 unsupported、1 E3 风险和 1 运行失败。两批都没有严格准入死亡。

本阶段扩展了单敌动态名单绑定和全队能量执行。多人友方目标、抽牌堆揭示、二次目标、新的未捕获执行帧、死亡终局等价性和自动出牌 Power 消费仍待验证或修复。没有修改神经网络结构、训练目标或规模化训练配置。

全量回归 162 通过、1 跳过，五角色各完成 5/5。冻结 NOSL 定向 19 通过，F4 6、LS2A 7、LS2B 5，II-A 原生路线、II-B 公开等价性、II-C 死亡见证均复验。II-D 对比不同 RNG 下的公开概率一致。两次参数更新的中断恢复与连续运行轨迹、模型、Adam 和 RNG 相同。

[覆盖矩阵](../experiments/m1-nosl3c-iid/coverage.json.gz) · [构建与验证证据](../experiments/m1-nosl3c-iid/evidence.json)
