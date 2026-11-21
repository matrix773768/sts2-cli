# II-I.7 Glimpse Beyond 效果镜像

隔离候选 `0.51.5-iii.7` 继承 II-I.6，锁定 II-H.7 战斗宿主、STS2 v0.113.1 Build 26660232 和 CoreCLR 9.0.7。

原生 OnPlay 按同侧顺序遍历活着的玩家。每位接收者先通过 Soul.Create 生成整批独立实例，再由出牌者作为生成来源，将这些牌逐张随机插入接收者的抽牌堆。镜像复用固定卡牌生成与随机入堆路径，每次插入由 Shuffle RNG 按当时的牌堆长度取位。数量来自卡牌动态变量，普通版为 3，升级版为 4。

## 定向验收

- 独立单人原生夹具从非空抽牌堆开始。普通版新增 3 张 Soul，升级版新增 4 张。两组抽牌堆顺序、完整 RNG、续体和合法菜单均精确匹配。Defend 对照的抽牌堆与 RNG 保持一致。
- II-E `1:000000` 冻结索引 0–11 的续体戳与 II-I.5 相同，索引 12 的抽牌堆与 RNG 差异消除。13 步均精确匹配，前缀结束时战斗仍在进行。原风险复放中 Glimpse Beyond 的镜像缺口消除，其它诊断保留。
- 同根沿用 pair16 固定配置重采一次，关闭优化，独立账本落在 `logs/iii7-resample/training.sqlite`。新轨迹第 5 个动作是 Soul，第 58 个动作打出 Glimpse Beyond。73 个原生边界通过，终局获 `exact_native_match` 和 `admissible_predicted_win`。
- Legion of Bone 四组原生夹具与 II-I.6 的记录逐项一致。

[构建与逐根证据](../experiments/m1-nosl3c-iii7/evidence.json)

## 最小复现

使用新的输出目录和锁定的 II-H.7 战斗宿主。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/new-iii7-solver'
$h = 'experiments/m1-nosl3c-iii7'
python "$h/build_solver.py" $s
python "$h/verify_glimpse.py" logs/new-iii7-effects --solver $s
python "$h/verify_root.py" prefix logs/new-iii7-prefix logs/nosl3c-iie-broad --solver $s --case nosl3c-iie-broad:1:0
python "$h/verify_root.py" risks logs/new-iii7-risks $s
python "$h/verify_root.py" resample logs/new-iii7-resample $s
python experiments/m1-nosl3c-iii6/verify_legion.py logs/new-iii7-legion --solver $s
```
