# II-I.3 Underworld 效果镜像

隔离构建 `0.51.5-iii.3` 继承 II-I.2，配对 II-H.7 战斗宿主及 CoreCLR 9.0.7。

原生先完成出牌动画，再以卡牌为来源向拥有者施加一层 Underworld Power。升级移除 Exhaust。后续钩子只对同侧、由其他玩家或非自身宠物发起、具有正伤害的有动力攻击施加 Doom，层数为总伤害乘 Power 层数。敌侧回合结束移除该 Power。Solver 注册实际 OnPlay 处理器，保留现有伤害与回合结束钩子。正向友方攻击条件经原生方法核对，固定单人宿主实测覆盖自身攻击排除和清理。

## 定向验收

- 普通版与升级版各比较四步完整续体和合法菜单。普通版有 Exhaust，升级版已移除。两版施加一层 Underworld；下一手自身 Strike 造成 6 伤害且未施加 Doom。敌侧回合结束后 Underworld 消失，并在下一轮保持清除。
- II-D `0:000025` 两个冻结动作均精确匹配。直接风险探针在索引 0 仍报告 Sic ’Em 的 `MethodMirrorIncomplete`，但两步均未观察到实际续体差异。索引 1 的 Underworld `MethodNotMirrored` 已消除。
- 同根以 pair16 固定策略重采一次，关闭优化，得到 `exact_native_match` 和 `admissible_death`。新轨迹单独保存。
- 普通及升级 Hibernate 夹具完整通过，续体戳与 II-I.2 一致。

[构建身份与定向证据](../experiments/m1-nosl3c-iii3/evidence.json)

## 最小复现

从仓库根使用已锁定的 II-H.7 宿主及新输出目录。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/new-iii3-solver'
$h = 'experiments/m1-nosl3c-iii3'
python "$h/build_solver.py" $s
python "$h/verify_underworld.py" logs/new-iii3-effects --solver $s
python "$h/verify_root.py" prefix logs/new-iii3-prefix logs/nosl3c-iid-release-independent --solver $s --case nosl3c-iid-release-independent:0:25
python "$h/verify_root.py" risks logs/new-iii3-risks $s
python "$h/verify_root.py" resample logs/new-iii3-resample $s
python experiments/m1-nosl3c-iii2/verify_hibernate.py logs/new-iii3-hibernate --solver $s
```
