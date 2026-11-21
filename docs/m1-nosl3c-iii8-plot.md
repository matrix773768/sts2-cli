# II-I.8 Regent Plot+ 阻断风险

隔离候选 `0.51.5-iii.8` 继承 II-I.7，使用 II-H.7 战斗宿主、STS2 v0.113.1 Build 26660232 和 CoreCLR 9.0.7。

## 冻结复放

II-I.7 基线在 II-E `1:000003` 索引 0–6 精确匹配。索引 7 的 Plot+ 首次分歧，预测缺少原生的三层 `DRAW_CARDS_NEXT_TURN_POWER`。II-I.8 的八个索引全部精确匹配，前缀结束时战斗继续。Plot+ 原始阻断风险消除，Void Form、Parry、Monologue 的镜像诊断仍在。

## 原生夹具

原生 OnPlay 按同侧顺序给存活玩家施加延迟抽牌 Power，施加者为出牌者，来源为当前 Plot 实例。此效果无选择、额外牌区操作或 RNG 调用。镜像复用共享 Power 路径，层数取卡牌动态变量。单人夹具比较了普通版、升级版和 Defend 对照的完整续体及合法菜单。Plot 出牌时抽牌堆和 RNG 保持一致，下回合分别抽到 7、8 张并移除 Power，对照抽到 5 张。

Glimpse Beyond 普通、升级和 RNG 对照与 II-I.7 的记录一致。Void Form 星费合法性夹具与 II-H.7 的记录一致。

## 同根重采

沿用 pair16 固定配置及预算，仅采一次，关闭优化，独立账本为 `logs/iii8-resample/training.sqlite`。第 3 次决策打出 Quasar，第 4 次选择 Panache，第 5 次确认选择时预测报 `PendingChoice`，详情为 `Candidate is missing from its source`。该路线尚未打出 Plot，严格结果为 `unsupported / semantic_unverified`，未进入终局原生认证。Quasar 生成选牌缺陷单独登记。

[构建与定向证据](../experiments/m1-nosl3c-iii8/evidence.json)

## 最小复现

从仓库根使用新的输出目录。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$h = 'experiments/m1-nosl3c-iii8'
$s = 'logs/new-iii8-solver'
$l = 'logs/nosl3c-iie-broad'
python "$h/verify_root.py" prefix logs/new-iii8-baseline $l --solver logs/m1-nosl3c-iii7-candidate --case nosl3c-iie-broad:1:3
python "$h/build_solver.py" $s
python "$h/verify_plot.py" logs/new-iii8-effects --solver $s
python "$h/verify_root.py" prefix logs/new-iii8-prefix $l --solver $s --case nosl3c-iie-broad:1:3
python "$h/verify_root.py" risks logs/new-iii8-risks $s
python "$h/verify_root.py" resample logs/new-iii8-resample $s
python experiments/m1-nosl3c-iii7/verify_glimpse.py logs/new-iii8-glimpse --solver $s
python experiments/m1-nosl3c-iih7/verify_legality.py logs/new-iii8-legality --solver $s
```
