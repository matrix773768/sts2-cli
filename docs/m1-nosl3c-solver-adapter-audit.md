# M1-NOSL3C-II-F Solver 适配与语义认证

基线 `37c1e52`，游戏 0.113.1／Build 26660232，CoreCLR 9.0.7。原生认证继续使用 II-D 的 Solver `0.51.5-iid.1`。新增离线直接复放宿主加载原始 Solver 0.51.5，验证已加载哈希后，按原路线执行 `PlanAction`。探针调用 Replay，绕过 Search、剪枝与旧教师动作白名单。

## Solver 与适配层对照

原始 Replay 可以执行已绑定的卡牌和目标。在两组抽查中复放 17 条可提取动作的前缀。部分前缀可正常继续，部分停在实际 `PendingChoice`，其余触发预测风险。待决选择需要相应玩家决定，只有前缀的档案不能据此证明原始 Solver 无法恢复，也无法证明已拥有完整合法菜单。三条 II-C 原路线起点没有可提取动作，另有一条 IID 运行失败未保存轨迹，全部保留在分母。

对照发现三类情况。

- II-C 原死亡样本 000002 在原始 Solver 完整结束为死亡。原始 Replay 无风险，分歧位于敌方阶段死亡后的历史窗口字段。
- II-C 000013 从原始 Solver 直接执行至胜利，仍残留 `FREE_ATTACK_POWER=1`。原生没有该 Power，继续失格。此次未修改底层消费逻辑。
- II-C／II-E 多个 unsupported 前缀可在原始 Replay 中执行至待决选择，另有若干直接触发风险。Solver 的搜索目标枚举仅对 AnyEnemy 展开，对于其余类型不能直接作为完整公开菜单。现有 NOSL 继续复用 Solver 可打性、费用、动作绑定和续体。抽牌堆可见性、手动二次目标和未知执行帧仍需独立实证。

原生菜单审计现先核验 `can_play` 再将手动目标加入预期菜单。含潜在合法目标但费用不可支付的回归输入在旧检查失败，新检查通过。对同一输入开启合法出牌后，缺失动作仍会被抓住。没有观察到冻结样本中的新增准入由此修复直接触发。

## 认证

- `exact` 要求原始逐边界续体核验和 II-E 独立终局合同通过。
- `semantic` 允许明确版本化的死亡窗口等价。
- `diagnostic` 同时保存精确状态和语义结论，训练资格仅来自精确匹配。

死亡规则 `sts2.nosl.iif.enemy-death-window.v1` 限定已锁定的游戏、Solver 和 runtime。最后一个动作必须是在玩家阶段发起的结束回合，原生与预测在同一回合确认死亡。紧邻致死动作的前一稳定边界须精确匹配。原生再收到结束回合后仍为同一死亡终局，原生续体也保持不变。在完整原始续体字符串中，仅允许唯一的 `Y` 和 `AttackStarts` 窗口字段变化。预测值须等于前一玩家窗口，原生须为零。所有其它续体字节包括牌序、RNG、敌人实体、Power、资源和 `FlameHp` 必须一致。额外核对 game_over、HP、最大 HP、格挡、金币和资源槽。保留原始字段与前驱证据。

这沿用了 E3 对当前侧与玩家侧历史计数口径的发现，新增证据是死亡后尝试继续的独立原生复放。规则没有放宽 E3 胜局、可继续状态或清理了实体的死亡。多个死亡路径证明了该窄规则的可用范围，无法进一步证明复杂监听器中间序列相同。负例覆盖 HP、格挡、能量、Power、抽牌顺序、RNG、实体状态、胜负、金币、阶段和缺失合法动作。

## 冻结复放

| 来源 | 尝试 | 精确匹配 | 符合死亡语义规则 | 语义未确定 | 实质不一致 | 缺路线 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| II-C 固定 20 根 | 20 | 2 | 5 | 8 | 2 | 3 |
| II-D 独立 30 根 | 30 | 13 | 7 | 7 | 2 | 1 |
| II-E 全池 15 根 | 15 | 5 | 1 | 7 | 2 | 0 |

原动作按原公开槽位与选择身份重绑，复放检查原公开观测。归档的失格前缀有些在最后已知动作后仍未结束，这些路线仍无终局资格。精确死亡结果也包含 II-E 对胜利回调依赖的既有修复，不能算作新语义规则收益。语义匹配列只表示诊断发现的规则适配，诊断运行本身保持原有准入限制。

## v4 接入

将证据模式、规则和来源哈希加入运行身份。严格账本仍保留每个终局前缀与审计校验值，生产行只保存资格级别与证据链。优化继续使用冻结 v4 损失、Critic、回报和行为复算。语义准入检查通过后仅在进程内适配旧优化器的准入接口，账本始终保留语义标签。IIF 入口当前使用冷审计进程。

## 复现

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$iif = 'experiments/m1-nosl3c-iif'
$solver = 'logs/m1-nosl3c-iid-solver'
python "$iif/build_host.py"
python "$iif/direct_probe.py" logs/iif-direct logs/nosl3c-iic-random-final --solver $solver
python "$iif/compare_frozen.py" logs/iif-replay logs/nosl3c-iic-random-final logs/nosl3c-iid-release-independent logs/nosl3c-iie-broad --solver $solver
python "$iif/validate.py" logs/iif-replay/nosl3c-iic-random-final.json
python "$iif/train.py" logs/iif-train --solver $solver --config "$iif/integration.json" --mode semantic
```

冻结输入账本可由 II-C、II-D、II-E 原复现命令生成。切换认证模式时使用不同输出目录。未启动正式课程。


## 集成回归

同一初始策略的三条工程轨迹中，exact 仅准入一胜，diagnostic 另外识别两条可等价死亡且仍只准入一胜，semantic 实际准入一胜两死。semantic 从更新 0 检查点恢复后执行一次真实更新，68 个决策的行为 logp 最大误差为 1.19e−7。跨模式恢复拒绝。全量 162 通过、1 跳过，冻结 NOSL 定向 19、F4 6、LS2A 7、LS2B 5，II-A 至 II-E 原生探针复验。未启动长期课程。

[逐路线归因](../experiments/m1-nosl3c-iif/coverage.json.gz) · [死亡证明](../experiments/m1-nosl3c-iif/death-proof.json.gz) · [验证证据](../experiments/m1-nosl3c-iif/evidence.json)
