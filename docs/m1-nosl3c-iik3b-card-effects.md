# II-K.3B — 四项出牌机制

起点 `port/v0.113.1@6aa168d`。累计候选 `0.51.5-iik.3b` 继承 II-K.2.4，DLL SHA-256 为 `b4db8cae5abada95a3a51caac31bbae9f356fb553949b3c7d4b14ea10d181c53`，与构建清单一致。正式全量验收基线为 `0.51.5-iij.4`。

## 实现与原生夹具

| 机制 | 实现与原生依据 | 单人原生夹具 |
| --- | --- | --- |
| Sneaky | 从卡牌变量给出牌者施加 Power。沿用已有攻击后格挡镜像，原生 `AfterCardPlayed` 检查出牌者与 Power 持有者不同且卡牌类型为攻击 | 普通版 1 层，升级版再叠 2 层，总计 3。本人 Strike 格挡保持 0。5.2 秒 |
| One for All | 按原生战斗玩家顺序施加，持有者是接收玩家，施加者是出牌者。加法钩子只计该持有者卡牌的有动力攻击，排除 X 费。手动按 `EnergySpent`，自动按 `EnergyValue`，无出牌记录按当前修正费用 | 普通 3 层，升级 4 层。累计 7 层后 FTL 打 12，付费 Strike 打 6。Bullet Time 后减费至零的 Strike 打 9，X 费 Skewer 打 8。Havoc 自动打出的付费 Strike 打 6，零费 FTL 打 9。四例分别 5.1、5.3、5.1、5.1 秒 |
| Tank | 自身施加 Tank。原生的新施加回调只向其他存活玩家授予 Guarded，移除时按施加者清理。Tank 和 Guarded 各自在持有者受到有动力攻击时读取原生倍率，分别为 1.5 和 0.5 | Punch Construct 敌击续体精确。跨职业夹具中奥斯蒂有 Die for You 且无 Guarded，Offering 的 6 点无动力自伤精确，随后敌击与奥斯蒂承伤的续体精确。4.7、5.6 秒 |
| Blade Symphony | 按原生队友顺序，仅给存活玩家生成普通 Shiv，创建者为空。沿用逐张加入手牌的生成入口 | 普通／升级均在本人手牌尾部生成两张。上限夹具依次达到 8、9、10 张手牌，最后一张溢出的 Shiv 进弃牌堆，手牌顺序及完整戳精确。5.0、5.3 秒 |

原生调用与分支摘录在本地 `logs/iik3a-native.il`、`logs/iik3b-native.il`、`logs/iik3b-tank.il` 和 `logs/iik3b-guard.il`。现有合成宿主仅启动单玩家。Sneaky 另一玩家攻击正例、One for All 多玩家施加、Tank 其他真人玩家的 Guarded 施加／移除及承伤、Blade Symphony 多人发牌顺序均未独立跑局认证。未用低成本夹具单独覆盖 One for All 的无出牌记录伤害分支。

## 冻结复放和同根重采

四条旧稳定前缀全部精确，原阻断动作均完成并获得精确续体。每根随后仅执行一次重采，直接从 II-J.5B SQLite 读取原规格、原模型和整数种子，预算 128、优化关闭。各重采保留完整历史前缀。

| 见证 | 冻结决策／原阻断 | 重采结果 | 复放／重采墙钟 |
| --- | --- | --- | --- |
| pair16 `0:000014` Sneaky | 19／18 | 20 决策、20 边界，严格胜局 | 5.3／11.4 秒 |
| holdout `0:000014` One for All+ | 3／2 | 22 决策、22 边界，严格胜局 | 5.4／9.5 秒 |
| holdout `0:000027` Tank | 6／5 | 15 决策、15 边界，严格败局 | 5.6／9.1 秒 |
| holdout `1:000013` Blade Symphony | 20／19 | 30 决策、30 边界，严格胜局 | 6.0／9.1 秒 |

四根均为 `exact_native_match`，无新首差。两条 Silent 路线的候选复放未发布捕获阻断，后续重采均完成严格认证。该结果只覆盖这两条实跑路线。候选编译一次，耗时 42.40 秒，有一条 CS9124 警告。未运行全量套件。

## 复现

从仓库根执行，使用新输出目录。每条命令可单独重定向日志。复放与重采按套件和根读取原账本。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$h = 'experiments/m1-nosl3c-iik3b'
$r = 'logs/new-iik3b'
python "$h/build_solver.py" "$r-solver"
python "$h/verify_cards.py" "$r-fixtures" "$r-solver"
python "$h/verify_roots.py" "$r-routes" "$r-solver"
python "$h/verify_roots.py" "$r-resample" "$r-solver" "$r-routes"
```
