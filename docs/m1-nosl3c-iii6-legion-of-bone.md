# II-I.6 Legion of Bone 效果镜像

隔离 Solver `0.51.5-iii.6` 继承 II-I.5，使用 II-H.7 战斗宿主与 CoreCLR 9.0.7。

原生 Legion of Bone 在出牌动画后快照所有存活玩家，按顺序对每位玩家调用奥斯提召唤。普通版召唤量为 6，升级版为 8。Solver 注册正式 OnPlay 处理器，复用共享召唤路径创建奥斯提、增加存活奥斯提的当前与最大生命，或复活已有实例。原生召唤钩子检查未发现影响本次生命值和战斗状态的专有规则。多人接收顺序和存活筛选依据原生实现，本轮独立夹具使用单人宿主。

## 定向验收

- 普通及升级版各验证两种起始状态。奥斯提不存在时创建为 6/6 或 8/8。先用 Bodyguard 召唤 5/5 时，原实例变为 11/11 或 13/13。四组续体和合法菜单精确匹配，`Die For You` 保持一层，后续 Poke 均造成 6 伤害。
- II-D `0:000027` 的 13 个冻结动作全部精确匹配，包括索引 12 的复活。旧奥斯提字段差异及 Legion of Bone 的 `MethodNotMirrored` 消除。原有其它镜像提示保留。冻结前缀结束时战斗仍在进行。
- 同根按 pair16 固定策略重采一次，关闭优化。获得 `exact_native_match` 和 `admissible_death`，新轨迹单独保存。
- Calcify 全部原生夹具通过，续体戳与 II-I.5 一致。

[构建身份与定向证据](../experiments/m1-nosl3c-iii6/evidence.json)

## 最小复现

从仓库根使用锁定的 II-H.7 宿主及新的输出目录。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/new-iii6-solver'
$h = 'experiments/m1-nosl3c-iii6'
python "$h/build_solver.py" $s
python "$h/verify_legion.py" logs/new-iii6-effects --solver $s
python "$h/verify_root.py" prefix logs/new-iii6-prefix logs/nosl3c-iid-release-independent --solver $s --case nosl3c-iid-release-independent:0:27
python "$h/verify_root.py" risks logs/new-iii6-risks $s
python "$h/verify_root.py" resample logs/new-iii6-resample $s
python experiments/m1-nosl3c-iii5/verify_calcify.py logs/new-iii6-calcify --solver $s
```
