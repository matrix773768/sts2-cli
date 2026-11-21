# II-H.6 Fogmog 免费攻击 Power

基线为 `9ed3c42`。隔离构建 `0.51.5-iih.6.1` 继承 II-H.5.1 及 II-H.4 修复。定向验收使用 CoreCLR 9.0.7。II-H.2 仍是最近一次全量验收构建。

II-D `0:000002` 在动作索引 22 的 `end_turn` 进入败局。Unrelenting 先施加一层 `FREE_ATTACK_POWER`，玩家之后符合条件的攻击会在出牌前消耗该层数。见证路线在致死敌方行动前仍持有一层。原生死亡清理先检查 Power 自身的移除条件，再询问该战斗中的监听器。场上的 `IllusionPower` 会阻止移除增益和临时 Power，且这个钩子不检查 Power 的归属。Solver 原先只在死者自身持有幻影 Power 时应用这个条件。

共享死亡清理现在从当前预测战斗的有效监听器查找幻影，沿用原生 Power 的移除条件和幻影钩子。认证、状态导出及免费攻击生成与消耗逻辑维持原样。

## 定向验收

- Fogmog 历史路线完整复放 23 个动作，获得 `exact_native_match` 和 `certified_death`。
- 独立原生夹具逐步比较完整续体戳和出牌前合法菜单。Unrelenting 施加一层，防御牌保留该层数，Strike 消耗该层数。死亡时，场上幻影保留尚未消耗的层数。无幻影对照中，死亡清理该层数。
- Living Fog 历史败局与吞噬暗影／Flutter 历史胜局均精确匹配，终局戳与 II-H.5 一致。

[构建身份与定向证据](../experiments/m1-nosl3c-iih6/evidence.json)

## 最小复现

从仓库根运行，使用新的输出目录。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/new-iih6-solver'
$l = @('logs/nosl3c-iic-random-final','logs/nosl3c-iid-release-independent','logs/nosl3c-iie-broad')
python experiments/m1-nosl3c-iih6/build_solver.py $s
python experiments/m1-nosl3c-iih6/verify_lifecycle.py logs/new-iih6-lifecycle --solver $s
python experiments/m1-nosl3c-iih3/replay.py logs/new-iih6-targeted @l --solver $s --workers 1 --case nosl3c-iid-release-independent:0:2 --case nosl3c-iic-random-final:0:19 --case nosl3c-iie-broad:2:1
```
