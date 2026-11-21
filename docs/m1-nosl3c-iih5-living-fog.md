# II-H.5 Living Fog 召唤物生命周期

基线为 `4766fd9`，隔离构建 `0.51.5-iih.5.1` 继承 II-H.4.1，运行时为 CoreCLR 9.0.7。II-H.2 仍是最近一次全量验收构建。

II-C `0:000019` 在动作索引 31 结束回合时，Gas Bomb 的爆炸击杀玩家。原生 `GasBomb.ExplodeMove` 等待攻击结算后，对仍存活的炸弹调用 `CreatureCmd.Kill(force: false)`。Solver 此时从敌方行动结算提前返回，跳过动作尾部，留下 7 HP 的炸弹和一层 `MINION_POWER`。修复让爆炸在发布败局前走完现有动作尾部，通过普通击杀触发共享实体移除和 Power 清理。认证与状态导出保持原样。

## 定向验收

- **Living Fog 历史路线**：II-C `0:000019` 消费全部 32 个动作，取得 `exact_native_match`，终局为 `certified_death`。
- **召唤物正负例**：独立原生与 Solver 在三个回合的完整续体和合法菜单一致。召唤前无炸弹，Bloat 后保留 7 HP 的炸弹和一层 Minion，下一回合非致死爆炸后两者均已移除。
- **吞噬暗影／Flutter 回归**：II-E `2:000001` 消费全部 15 个动作，取得 `exact_native_match` 和 `certified_win`。终局戳与 II-H.4 一致。

[构建身份与定向证据](../experiments/m1-nosl3c-iih5/evidence.json)

## 最小复现

从仓库根运行，使用新的输出目录。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/new-iih5-solver'
$l = @('logs/nosl3c-iic-random-final','logs/nosl3c-iid-release-independent','logs/nosl3c-iie-broad')
python experiments/m1-nosl3c-iih5/build_solver.py $s
python experiments/m1-nosl3c-iih5/verify_lifecycle.py logs/new-iih5-lifecycle --solver $s
python experiments/m1-nosl3c-iih3/replay.py logs/new-iih5-targeted @l --solver $s --workers 1 --case nosl3c-iic-random-final:0:19 --case nosl3c-iie-broad:2:1
```
