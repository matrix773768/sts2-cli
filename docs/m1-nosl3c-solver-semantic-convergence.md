# M1-NOSL3C-II-H 战斗语义诊断检查点

起点为 `port/v0.113.1` 的 `250c87396076b7fd0d5abfa5b512e768c02d72cb`。原生复放使用 STS2 v0.113.1／Build 26660232 和 CoreCLR 9.0.7。隔离 Solver 为 `0.51.5-iig.2`，SHA-256 为 `8d1c9786f88e9057bbdf5d2cf7298cafd52f23b7db532b7ea295d7280f02c41d`。游戏 DLL SHA-256 为 `62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3`。诊断报告包含宿主、原始 Solver 和证据文件的构建身份与哈希。

## 本次实测

- 65 条冻结路线逐条复放。每条分类与归档一致。34 条完整认证为 16 胜、18 死，另有 5 条实质差异、8 条 Solver 风险、4 条 E3 和 14 条缺历史动作的尝试。最后一组含一条原账本执行失败。
- 四条 E3 复现了归档中的字段差异。II-C 000015 和 II-D 000000 仅差 Y，II-E 000004 另差 AttackStarts，II-C 000006 还差 P。重复结束回合的原生探针提供胜利锁定证据。奖励等价与 Power 清理顺序仍待证明。
- 原始 Solver 对八条前缀均再次报告风险。冻结独立前缀证据中七条有具体状态差异，另一条在菜单或动作对比处停止。风险报告位置与首个独立对比位置分别保留。
- 五条实质差异仍见于 Living Fog 实体、Fogmog 免费攻击、Hunter Killer 合法菜单、Sovereign Blade 手牌和 Consuming Shadow／Flutter Power。

## 复现

在仓库根目录执行。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$f = 'experiments/m1-nosl3c-iig-completion'
$s = 'logs/m1-nosl3c-iig-completion-candidate'
$l = @('logs/nosl3c-iic-random-final', 'logs/nosl3c-iid-release-independent', 'logs/nosl3c-iie-broad')
python experiments/m1-nosl3c-iih/diagnose.py logs/iih-diagnostic.json @l
python "$f/replay_archive.py" logs/iih-baseline @l --solver $s
python "$f/verify/terminal_windows.py" logs/iih-e3 @l --solver $s
python "$f/verify/risk_original.py" logs/iih-risk @l --solver logs/m1-nosl3c-iig-certified
```

诊断入口按账本、批次和根位置连接冻结证据，使用只读 SQLite 连接读取归档动作。输出包含原生公开状态、可用的预测状态与字段差异、风险和终局窗口。空字段表示原证据缺少对应该项。字段差异记录在最早已归档的对比边界，同一边界内的字段顺序无法证明事件因果。

## 待完成

仍需追踪 E3 原生终局钩子与结算，定位五条实质差异及八条预测风险的共享机制，构建独立 II-H Solver，并用原生正负例重证。其后仍需同根补采、旧样本配对、新 60 根全卡池验证、指定回归和 v4 集成训练。本检查点保留现有准入规则，尚未建立开启大规模高 HP 训练所需的证据。

## II-H Completion 的 Solver 修复

隔离构建 `0.51.5-iih.1` 将预测抽牌与出牌开始事件标记为各自的阵营和回合，并在两种续体克隆中保留标记。敌方阶段的续体将原生根历史和同一窗口的预测事件合并，按原生 `HappenedThisTurn` 口径导出 Y 与 AttackStarts。玩家侧内部计数继续供卡牌和 Power 使用。修改由 [隔离构建脚本](../experiments/m1-nosl3c-iih/build_solver.py) 应用。

三条纯历史窗口见证在原动作 `end_turn` 后精确匹配原生终局续体，原生重复结束回合仍停在奖励界面。II-C 000006 同时修复了窗口差异，但原生 Frail 为 3 层，预测为 2 层，仍为实质差异。当前线索是 `CorePowerSupport.TriggerEnemySideTurnEndEffects` 在 Doom 结算后继续执行 `TickDurations`，尚待原生监听器顺序验证。三条终局的战斗续体可精确比较，奖励生成与监听器尾部仍缺独立对照，四条路线继续保持 E3 隔离。

固定 65 条路线逐条核对，全部分类保持。原有 34 条认证现在全部精确匹配，其中 16 胜、18 死。五条实质差异和八条预测风险保持原分类。未重跑旧独立 16/60 根、未采集新 60 根、未做候选构建的 v4 训练验收。

复现时先用 `python experiments/m1-nosl3c-iih/build_solver.py logs/m1-nosl3c-iih-candidate` 构建，将上文的 `$s` 改为新输出目录，再执行归档和终局窗口复放。可用 II-G Completion 的 `probe_prefix.py` 对照最终精确戳，E3 个案为 II-C `0:15` 与 `0:6`、II-D `0:0`、II-E `1:4`。
