# II-I.5 Calcify 与 Necrobinder 共享效果

隔离构建 `0.51.5-iii.5` 继承 II-I.4，使用 II-H.7 战斗宿主与 CoreCLR 9.0.7。

Calcify 正式 OnPlay 镜像以原卡为来源给拥有者施加 4 层 Power，升级施加 6 层。旧补偿分支迁移至正式镜像，避免重复施加。原生加成钩子只给自己的奥斯提的有动力攻击加上等同于层数的伤害。现有共享加算伤害路径已能执行该钩子。

Pull Aggro 原生先召唤，再给自身格挡。旧预测通过通用格挡和独立召唤补偿覆盖数值，仍报告部分镜像。两条冻结路线的 Pull Aggro 边界均精确匹配。该卡未涉及 Calcify 的 Power 应用或伤害加算，本轮保留原有实现。

## 定向结果

- **独立夹具**：无 Calcify 时奥斯提的 Poke 为 6 伤害，普通版为 10，升级为 12。玩家 Strike 在三组均为 6。Calcify 层数跨回合保留，完整续体和合法菜单均匹配。夹具同时覆盖共享召唤和伤害路径，Outrage 普通及升级回归与 II-I.4 一致。
- **II-D `0:000027`**：索引 0–11 精确匹配，索引 2 的 Calcify 缺口消除，索引 3 的 Pull Aggro 风险提示保留。首个实际差异在索引 12 的 Legion of Bone，原生奥斯提字段为 `4/8/8`，预测为 `4/0/4`。
- **II-E `1:000000`**：索引 0–11 精确匹配，索引 1 的 Pull Aggro 风险提示保留，索引 8 的 Calcify 缺口消除。首个实际差异在索引 12 的 Glimpse Beyond，涉及抽牌堆中新增的三张 Soul 及对应 RNG。
- **同根重采**：两根通过目标边界后各用 pair16 固定策略重采一次，关闭优化。II-D 第三个动作 Legion of Bone、II-E 第五个动作 Glimpse Beyond 分别触发 `prediction_unsupported`，两根均未获严格认证。

[构建身份与定向证据](../experiments/m1-nosl3c-iii5/evidence.json)

## 最小复现

从仓库根使用锁定的 II-H.7 宿主及新的输出目录。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/new-iii5-solver'
$h = 'experiments/m1-nosl3c-iii5'
python "$h/build_solver.py" $s
python "$h/verify_calcify.py" logs/new-iii5-effects --solver $s
python "$h/verify_roots.py" prefix logs/new-iii5-prefix logs/nosl3c-iid-release-independent logs/nosl3c-iie-broad --solver $s --case nosl3c-iid-release-independent:0:27 --case nosl3c-iie-broad:1:0
python "$h/verify_roots.py" risks logs/new-iii5-risks $s
python "$h/verify_roots.py" resample logs/new-iii5-resample $s 000027 000000
python experiments/m1-nosl3c-iii4/verify_outrage.py logs/new-iii5-outrage --solver $s
```
