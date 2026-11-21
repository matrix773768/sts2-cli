# II-H.8 Sovereign Blade 牌区与实例

基线为 `d00c2d6`。Solver 候选 `0.51.5-iih.8.1` 继承 II-H.4–H.7，与 II-H.7 原隔离 Headless 宿主配对，固定 CoreCLR 9.0.7。两个 DLL 的 SHA-256 及原生身份记录在证据中。最近一次全量验收仍为 II-H.2。

II-H 和 II-G Completion 在 II-E `0:000003` 的零基索引 27 记录手牌差异。Tyranny 确认耗尽旧刀后，原生手牌有一张 17 伤害的新刀，旧 Solver 缺失。原生 `CardSelectCmd.FromHand` 使用 Headless 选择器时跳过暂停通知，等玩家回合准备完成后才触发阵营回合开始。旧 Solver 却在消费选择前提前触发 Furnace，此时旧刀仍在手牌，Forge 只加伤害，没有创建新刀。

隔离 Solver 现在等回合准备及选择效果结算完毕，再触发阵营回合开始。现有 Forge 逻辑按耗尽后的牌区判定是否需要新实例。此顺序已在 II-H.7 Headless 选择器下验证。

## 定向验收

- 历史路线完整复放 29 个冻结动作，双方在第 29 个动作后进入胜利奖励，25 个可取戳的稳定边界逐一精确匹配。普通归档比较在索引 28 停住，旧快照缺少新刀。定向复放先比较完整原生与预测菜单，只接受旧手牌恰好追加一张新刀，随后严格核对原动作的卡牌、目标及费用。冻结数据和认证逻辑保持原样。
- 独立原生正例耗尽旧刀后，旧刀留在耗尽区并增至 26 伤害，手牌新刀为 17 伤害。负例改耗尽防御牌，原刀留在手牌并增至 26 伤害，没有产生第二张刀。两端完整续体及合法菜单一致。
- Hunter Killer、Fogmog、Living Fog 与吞噬暗影／Flutter 历史回归均精确匹配，终局戳与 II-H.7 一致。
- II-H.7 Void Form 对照的合法性、星费与逐边界续体戳保持一致。

[构建身份与定向证据](../experiments/m1-nosl3c-iih8/evidence.json)

## 最小复现

从仓库根运行，复用 II-H.7 宿主 `logs/m1-nosl3c-iih7-host`，其 SHA-256 见证据。若宿主尚未构建，先执行 `python experiments/m1-nosl3c-iih7/build_host.py`。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/new-iih8-solver'
$l = @('logs/nosl3c-iic-random-final','logs/nosl3c-iid-release-independent','logs/nosl3c-iie-broad')
$h = 'experiments/m1-nosl3c-iih8'
$p = 'experiments/m1-nosl3c-iih7'
python "$h/build_solver.py" $s
python "$h/verify_forge.py" logs/new-iih8-forge --solver $s
python "$h/verify_history.py" logs/new-iih8-blade-history --solver $s --ledger $l[2]
python "$p/replay.py" logs/new-iih8-targeted @l --solver $s --workers 1 --case nosl3c-iie-broad:0:3 --case nosl3c-iid-release-independent:0:10 --case nosl3c-iid-release-independent:0:2 --case nosl3c-iic-random-final:0:19 --case nosl3c-iie-broad:2:1
python "$p/verify_legality.py" logs/new-iih8-legality --solver $s
```
