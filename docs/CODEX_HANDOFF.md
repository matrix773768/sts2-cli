# Codex 交接

## 当前基线

- 仓库 `matrix773768/sts2-cli`，分支 `port/v0.113.1`。每次启动先执行 `git status -sb` 和 `git rev-parse HEAD`。稳定化起点为 `5043f95467ee88a9e41375c51278a651b93ad14d`。
- STS2 v0.113.1 Build 26660232，CoreCLR **9.0.7**。最近一次全量验收构建为 Solver **0.51.5-iih.2**。
- 全量验收构建的 Solver DLL SHA-256 为 `d15ba0e66d2bf54dd1d00714c39f7b8ecc26b9a5b35b79ceb64277d4fd4a54dd`。
- E3 战斗认证 `sts2.nosl.iih3.enemy-side-exact-combat.v1`。保留 II-G Completion 死亡等价合同 `sts2.nosl.iig.completion.enemy-death-window.v1`。

## 工程状态

- 最新定向候选 `0.51.5-iih.8.1` 继承 II-H.4–H.7，复用 II-H.7 Headless。玩家回合准备先完成 Tyranny 选择及耗尽，再触发 Furnace。Sovereign Blade 的 29 个历史动作全部与原生精确对齐，牌区及实例正负例、四条历史回归和 Void Form 对照均通过。 [定向证据与复现](m1-nosl3c-iih8-sovereign-blade.md)

- II-H.7 隔离构建 `0.51.5-iih.7.1` 继承 II-H.4–H.6。Headless 合法菜单使用原生 `CanPlay` 和经战斗钩子修饰的固定星费。Hunter Killer 历史败局、Void Form 星费正负例及三条历史回归均通过。 [定向证据与复现](m1-nosl3c-iih7-hunter-killer.md)

- II-H.6 隔离构建 `0.51.5-iih.6.1` 继承 II-H.4 与 II-H.5。共享死亡清理按原生战斗监听器作用域应用幻影 Power 的移除条件。Fogmog 历史败局、免费攻击生命周期正负例及两条历史回归均通过。 [定向证据与复现](m1-nosl3c-iih6-fogmog.md)

- II-H.5 隔离构建 `0.51.5-iih.5.1` 继承 II-H.4.1。Gas Bomb 致死攻击后会先完成普通自杀和共享死亡清理，再发布败局。Living Fog 历史败局、召唤物原生正负例和吞噬暗影／Flutter 历史胜局均通过。 [定向证据与复现](m1-nosl3c-iih5-living-fog.md)

- II-H.4 隔离构建 `0.51.5-iih.4.1` 先同步伤害钩子的 Power 层数，再做共享死亡清理，并对齐吞噬暗影的终止条件。历史 II-E `2:000001` 已获精确胜局。II-H.2 仍为最近一次全量验收构建。 [定向证据与复现](m1-nosl3c-iih4-shared-combat.md)

- II-H.1 校准原生历史窗口，II-H.2 修复胜利锁定后的 Power 减层。II-H.3 的四条 E3 使用真实预测胜利、独立原生精确匹配和终局锁定获得严格战斗资格。原始风险反馈仍保留，训练使用派生反馈。
- 奖励和地图处置由独立原生流程负责。战斗审计的私有字段不进入 Actor。
- 旧 Solver 的四条 E3 负例已拒绝。新 E3 已实际进入 v4 更新。已逐项关闭五类历史实质差异，八条预测风险仍需后续研究。
- 稳定化的最新验收以 [报告](m1-nosl3c-iih3-stabilization.md) 为准。宿主超时按阶段记录，环境失败与规则差异分别判断。

## 保留数据

- `logs/nosl3c-iic-random-final`、`logs/nosl3c-iid-release-independent`、`logs/nosl3c-iie-broad` 三份冻结账本。
- `logs/m1-nosl3c-iih2-candidate`、`logs/m1-nosl3c-iih-reward-build`、`logs/m0-v5/dotnet9` 和 `lib`。
- II-H.3 审计、原生宿主失败目录、唯一模型检查点和 SQLite 训练事务账本均保留。不要重用旧输出目录。历史实验文件的删、移、压缩或清理需单独授权。 [存储审计](local-storage-audit.md)

## 最小复现

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/m1-nosl3c-iih2-candidate'
$h = 'experiments/m1-nosl3c-iih3'
$l = @('logs/nosl3c-iic-random-final','logs/nosl3c-iid-release-independent','logs/nosl3c-iie-broad')
python "$h/replay.py" logs/new-iih3-probe @l --solver $s --workers 1 --case nosl3c-iic-random-final:0:6
```

主要证据见 [H.3 证据](../experiments/m1-nosl3c-iih3/evidence.json)、[II-H.2 证据](../experiments/m1-nosl3c-iih/duration-evidence.json) 和 [语义收敛报告](m1-nosl3c-solver-semantic-convergence.md)。

## 额度节约

- 先读本文和当期报告，再查看相关源码。优先用 `rg`，限制搜索到需要的源码目录，不递归扫描整个 `logs/`。
- 大日志仅读失败摘要和相关尾部。用只读查询从 JSON、SQLite 提取根、阶段、分类及哈希，不将完整内容输出到上下文。
- 先定向测试，再在里程碑做全量验收。保留已确认实验的版本和证据，避免每次修改都全量复跑。
- 将大型原生套件分批执行。失败时记录首个异常、命令阶段、宿主日志路径和退出码。重试必须保留首次结果。
