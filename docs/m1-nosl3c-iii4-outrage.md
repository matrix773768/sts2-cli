# II-I.4 Outrage 效果补全

隔离 Solver `0.51.5-iii.4` 继承 II-I.3，使用 II-H.7 战斗宿主和 CoreCLR 9.0.7。

原生先结算单体攻击，再按同侧实体顺序向每个存活玩家生成一张该牌的克隆，置于其弃牌堆底。原生同侧列表包含出牌者自身，宠物和死亡实体被过滤。升级将基础伤害从 9 提到 13。Solver 现用原生攻击镜像和共享的玩家绑定克隆、生成牌入堆路径完成整个效果。终局由共享生成牌入口拒绝继续入堆。

## 定向验收

- 普通与升级夹具均核验完整续体及合法菜单。首击分别造成 9 和 13 伤害，各在弃牌堆留下原牌和一张同升级等级的副本。后续非致死攻击各增加一张，结束回合无新增副本。致死攻击的两端终局续体一致且无新增副本。实测覆盖单人，其他玩家的筛选及绑定依据原生方法核对。
- II-D `0:000028` 三个冻结动作均精确匹配，未观察到实际续体差异。直接探针仍记录索引 0 的 Battle Trance `MethodMirrorIncomplete`。索引 2 的 Outrage `MethodMirrorIncomplete` 已消除，探针未再触发预测风险。
- 同根用 pair16 固定策略及 128 动作上限重采一次，关闭优化，取得 `exact_native_match` 与 `admissible_death`。新轨迹单独保存。
- 普通及升级 Underworld 夹具通过，续体戳与 II-I.3 一致。

[构建身份与定向证据](../experiments/m1-nosl3c-iii4/evidence.json)

## 最小复现

从仓库根使用锁定的 II-H.7 宿主及新的输出目录。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/new-iii4-solver'
$h = 'experiments/m1-nosl3c-iii4'
python "$h/build_solver.py" $s
python "$h/verify_outrage.py" logs/new-iii4-effects --solver $s
python "$h/verify_root.py" prefix logs/new-iii4-prefix logs/nosl3c-iid-release-independent --solver $s --case nosl3c-iid-release-independent:0:28
python "$h/verify_root.py" risks logs/new-iii4-risks $s
python "$h/verify_root.py" resample logs/new-iii4-resample $s
python experiments/m1-nosl3c-iii3/verify_underworld.py logs/new-iii4-underworld --solver $s
```
