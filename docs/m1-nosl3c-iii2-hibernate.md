# II-I.2 Hibernate 效果镜像

隔离 Solver `0.51.5-iii.2` 继承 II-I.1 Hammer Time 和 II-H 修复，使用 II-H.7 Headless 与 CoreCLR 9.0.7。

原生 Hibernate 以该牌为来源向自身施加一层 Power，再凝聚冰霜球。普通版凝聚两颗，升级版三颗。冰霜球被动和激发先给自身格挡，持有 Hibernate 时再给其他玩家格挡。拥有者的下一回合开始钩子减去一层，并清理归零的 Power。

Solver 注册正式 OnPlay 镜像，复用共享 Power 应用和球槽结算。冰霜球转发读取分支中的 Hibernate 层数，回合开始继续使用已有减层镜像。多人转发范围依据原生方法检查，定向宿主的实际战斗为单人。

## 定向验收

- 普通及升级版各比较四个完整续体与合法菜单。先用 Coolheaded 放入一颗冰霜球。普通版填满三槽，升级版溢出一颗并获得 5 格挡。回合结束执行冰霜球被动，下一玩家回合开始清除一层 Hibernate。再过一轮，Power 仍已清除。
- II-D `0:000009` 的唯一冻结动作精确匹配。直接探针从 `HIBERNATE.OnPlay: MethodNotMirrored` 变为无预测风险。该冻结前缀结束于活动战斗。
- 同根沿用 pair16 固定策略及 128 动作上限重采一次，优化关闭。新轨迹通过十个边界，获得 `exact_native_match` 和 `admissible_predicted_win`，单独记账。
- 普通及升级 Hammer Time 的回归全部通过，续体戳与 II-I.1 一致。

[构建身份与定向证据](../experiments/m1-nosl3c-iii2/evidence.json)

## 最小复现

在仓库根使用已锁定的 II-H.7 宿主和新的输出目录。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/new-iii2-solver'
$h = 'experiments/m1-nosl3c-iii2'
python "$h/build_solver.py" $s
python "$h/verify_hibernate.py" logs/new-iii2-effects --solver $s
python "$h/verify_root.py" prefix logs/new-iii2-prefix logs/nosl3c-iid-release-independent --solver $s --case nosl3c-iid-release-independent:0:9
python "$h/verify_root.py" risks logs/new-iii2-risks $s
python "$h/verify_root.py" resample logs/new-iii2-resample $s
python experiments/m1-nosl3c-iii1/verify_hammer.py logs/new-iii2-hammer --solver $s
```
