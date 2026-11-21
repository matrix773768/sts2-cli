# II-I.1 Hammer Time 效果镜像

隔离 Solver `0.51.5-iii.1` 继承正式全量验收构建 `0.51.5-iih.8.1`。运行使用 II-H.7 Headless 与 CoreCLR 9.0.7。

原生 OnPlay 向自身施加一层 Hammer Time Power，并传递原卡牌作为来源。升级只将耗能从 2 降到 1。Forge 先创建或更新原玩家的刀实例，然后 Hammer Time 将同等锻造量复制给其他存活玩家。复制触发的 Forge 以 Hammer Time 为来源，原生监听器据此防止递归。Solver 注册正式 OnPlay 处理器，并在共享 Forge 更新后复用同一实例逻辑结算复制。原生多人复制条件依据原生方法检查。本机独立战斗宿主的夹具为单人，验证无其他玩家时不追加刀或伤害。

## 定向验收

- 普通及升级 Hammer Time 分别消耗 2 和 1 能量，各施加一层 Power。后续 Spoils of Battle 各生成一张 19 伤害的刀。完整续体和合法菜单与独立原生一致。II-H.8 Forge 耗尽与保留正负例均通过。
- II-E `1:000002` 的一个冻结动作在原生与预测间精确匹配，直接回放也已无风险。II-C `0:000003` 的七个冻结动作逐步精确匹配，Hammer Time 风险消失。首次剩余风险为索引 3 的 `BULWARK.OnPlay: MethodMirrorIncomplete`，该前缀未观察到对应续体差异。
- 两个同根各用既有 pair16 固定策略、初始化种子、策略种子与 128 动作上限重新采集一次，优化关闭。II-C 重采获 `exact_native_match` 和 `admissible_death`。II-E 重采在索引 42 打出 Sovereign Blade 时首次差异为 Solver 额外保留两层 `DRAW_CARDS_NEXT_TURN_POWER`，严格拒绝。新采集单独记录。

[构建身份和定向证据](../experiments/m1-nosl3c-iii1/evidence.json)

## 最小复现

在仓库根使用新的输出目录和已经锁定的 II-H.7 宿主。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/new-iii1-solver'
$h = 'experiments/m1-nosl3c-iii1'
python "$h/build_solver.py" $s
python "$h/verify_hammer.py" logs/new-iii1-hammer --solver $s
python "$h/verify_roots.py" prefix logs/new-iii1-prefix logs/nosl3c-iic-random-final logs/nosl3c-iie-broad --solver $s --case nosl3c-iie-broad:1:2 --case nosl3c-iic-random-final:0:3
python "$h/verify_roots.py" risks logs/new-iii1-risks $s
python "$h/verify_roots.py" resample logs/new-iii1-resample $s
python experiments/m1-nosl3c-iih8/verify_forge.py logs/new-iii1-forge --solver $s
```
