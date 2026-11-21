# II-H.7 Hunter Killer 合法动作菜单

基线为 `9317293`。隔离 Solver `0.51.5-iih.7.1` 继承 II-H.4–H.6，搭配新隔离 Headless 宿主，定向验收固定 CoreCLR 9.0.7。最近一次全量验收仍为 II-H.2。

## 首次分歧与修复

II-H 和 II-G Completion 均记录 II-D `0:000010` 在动作索引 2（从零计）的 `end_turn` 提交前遇到菜单差异。前一步打出升级 Void Form 并进入下一回合。双方均有 0 星，手牌索引 2 为升级 The Smith，目标类型为自身。该牌在原生公开菜单被标记为不可打出，Solver 菜单则提供星费为 0 的动作。

原生 `CardModel.CanPlay` 通过 `HasEnoughResourcesFor` 比较经战斗钩子修饰的星费。Void Form 在免费次数剩余时把星费降为 0。Headless 先取得原生 `CanPlay`，随后用未计入战斗钩子的 `CurrentStarCost` 再检查一次，错误拒绝了 The Smith。修复移除重复检查，公开固定星费改用原生的 `GetStarCostWithModifiers`。历史复放在这个边界及后续均精确匹配，完整续体和资源检查也在独立夹具逐步对齐。Solver 的动作生成、历史绑定及认证规则沿用原实现。

## 定向验收

- Hunter Killer 历史路线完整复放 10 个动作，获得 `exact_native_match` 和 `certified_death`。
- 独立原生夹具逐步比较完整续体和合法动作菜单。The Smith 的星费依次为 4、0、0、4。玩家在四个边界都持有 0 星，行动合法性依次为否、是、是、否。
- Fogmog、Living Fog、吞噬暗影／Flutter 三条历史路线均精确匹配，终局戳与 II-H.6 一致。

[构建身份与定向证据](../experiments/m1-nosl3c-iih7/evidence.json)

## 最小复现

从仓库根运行，使用新的输出目录。宿主构建目录 `logs/m1-nosl3c-iih7-host` 已存在时，可复用已构建的隔离宿主。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/new-iih7-solver'
$l = @('logs/nosl3c-iic-random-final','logs/nosl3c-iid-release-independent','logs/nosl3c-iie-broad')
$h = 'experiments/m1-nosl3c-iih7'
python "$h/build_solver.py" $s
python "$h/build_host.py"
python "$h/verify_legality.py" logs/new-iih7-legality --solver $s
python "$h/replay.py" logs/new-iih7-targeted @l --solver $s --workers 1 --case nosl3c-iid-release-independent:0:10 --case nosl3c-iid-release-independent:0:2 --case nosl3c-iic-random-final:0:19 --case nosl3c-iie-broad:2:1
```
