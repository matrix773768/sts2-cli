# II-H.4 共享死亡清理与 Power 同步

基线为 `d710d30`，STS2 v0.113.1 Build 26660232，CoreCLR 9.0.7。隔离构建 `0.51.5-iih.4.1` 保留 II-H.2。

## 原因与修复

II-E `2:000001` 的第 14 个动作索引是吞噬暗影。暗球激发击杀剩余 8 HP 的敌人。原生 `PowerCmd.Apply` 在战斗结束时拒绝施加 Power，`CreatureCmd.Kill` 则清理死者 Power。II-H.2 的续体错误保留吞噬暗影与敌人的 Flutter 5 层。

中间构建只对齐了吞噬暗影的施加条件。原路线仍多 Flutter 5 层，由此隔离出共享死亡清理问题。Flutter 的伤害倍率镜像读取 `PowerAmountPredictionState`，即使这次激发不会消耗 Flutter，也会缓存它的层数。共享死亡流程清零 Power 之后，卡牌尾部的同步又提交了旧缓存。最终构建先提交待同步的钩子层数，再清理死者 Power。吞噬暗影镜像同样遵守原生终止条件。规则认证保持原样。

## 定向验证

- 同一历史根和完整动作取得严格精确胜局。最终续体戳为 `69ba0999cc92fed137da36c3f936b9554e28221e03d05b6bd23d54659a99258e`。
- 独立非致死夹具中原生及预测均继续战斗，吞噬暗影仍为一层。完整续体和下一合法菜单一致。
- Living Fog 的在场 Gas Bomb、Fogmog 的免费攻击层数仍在原失败边界产生差异。Hunter Killer 和 Sovereign Blade 保持待修复。本轮仅验证上述历史见证和非致死夹具。

## 复现

先按 [短交接](CODEX_HANDOFF.md) 设置环境和 `$l`，在仓库根使用新输出目录。

```powershell
$s = 'logs/new-iih4-solver'
python experiments/m1-nosl3c-iih4/build_solver.py $s
python experiments/m1-nosl3c-iih4/verify_shadow.py logs/new-iih4-nonlethal --solver $s
python experiments/m1-nosl3c-iih3/replay.py logs/new-iih4-targeted @l --solver $s --workers 1 --case nosl3c-iie-broad:2:1 --case nosl3c-iic-random-final:0:19 --case nosl3c-iid-release-independent:0:2
```

从上一轮统计脚本提取了只读 [账本比较工具](../experiments/m1-nosl3c-iih3-stabilization/compare_journals.py)。现有冷跑与恢复账本直接比较时，身份、三个快照和 32 条语义轨迹均一致。

[构建身份及逐根证据](../experiments/m1-nosl3c-iih4/evidence.json)
