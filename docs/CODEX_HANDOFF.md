# Codex 交接

## 当前基线

- 仓库 `matrix773768/sts2-cli`，分支 `port/v0.113.1`。每次启动先执行 `git status -sb` 和 `git rev-parse HEAD`。稳定化起点为 `5043f95467ee88a9e41375c51278a651b93ad14d`。
- STS2 v0.113.1 Build 26660232，CoreCLR **9.0.7**。最近一次全量验收为 II-H.9.1，使用 Solver **0.51.5-iih.8.1**、II-H.7 战斗宿主与正确部署的常规 Headless。
- 全量验收构建的 Solver DLL SHA-256 为 `509eece4ef6a2be9e098e2b78d27e25736964e5c4ae5f7aa0d557c8680d77181`。
- II-H.7 战斗宿主 SHA-256 为 `b3f8ce1d862bdb98000bfeb90d701239e50be17034739c5c2ed18e26716150f0`。常规 Headless 部署至 `logs/iih9-main-host/bin/Debug/net9.0`。
- E3 战斗认证 `sts2.nosl.iih3.enemy-side-exact-combat.v1`。保留 II-G Completion 死亡等价合同 `sts2.nosl.iig.completion.enemy-death-window.v1`。

## 工程状态

- 最新定向候选 `0.51.5-iii.8` 补齐 Plot。II-E `1:000003` 的八步冻结前缀精确匹配，最后一条原始阻断风险消除。普通／升级延迟抽牌及 Glimpse Beyond、Void Form 回归通过。同根重采遇到独立 Quasar 生成选牌确认缺陷，未获严格认证。 [报告与复现](m1-nosl3c-iii8-plot.md)

- II-I.7 定向候选 `0.51.5-iii.7` 补齐 Glimpse Beyond。普通、升级和未打出对照通过。II-E `1:000000` 的 13 步冻结前缀精确匹配，同根重采获严格胜局，Legion of Bone 回归通过。[报告与复现](m1-nosl3c-iii7-glimpse-beyond.md)

- II-I.6 定向候选 `0.51.5-iii.6` 补齐 Legion of Bone。普通／升级创建及存活增血原生夹具通过。II-D 的 13 步全精确匹配，复活差异及 Legion 风险消除；同根重采获严格败局，Calcify 回归通过。 [报告与复现](m1-nosl3c-iii6-legion-of-bone.md)

- II-I.5 定向候选 `0.51.5-iii.5` 补齐 Calcify。普通／升级的奥斯提伤害及玩家攻击对照精确匹配。两个冻结前缀均通过 Calcify，首个实际差异都在索引 12。Pull Aggro 旧提示保留。两根重采因 Legion of Bone／Glimpse Beyond 不支持拒绝，Outrage 回归通过。 [报告与复现](m1-nosl3c-iii5-calcify.md)

- II-I.4 定向候选 `0.51.5-iii.4` 补全 Outrage 攻击后的同侧玩家克隆及弃牌堆落位。普通／升级正负例和三步冻结前缀均精确匹配。Outrage 风险消除，Battle Trance 原镜像缺口仍在。同根重采获严格败局，Underworld 回归通过。 [报告与复现](m1-nosl3c-iii4-outrage.md)

- II-I.3 定向候选 `0.51.5-iii.3` 补齐 Underworld，普通／升级效果、伤害排除和敌侧回合清理精确匹配。II-D 两步冻结前缀通过，Underworld 风险消除，Sic ’Em 原镜像缺口仍在。同根重采获严格败局，Hibernate 回归通过。 [报告与复现](m1-nosl3c-iii3-underworld.md)

- II-I.2 定向候选 `0.51.5-iii.2` 补齐 Hibernate，普通／升级效果和冰霜球触发、清理边界精确匹配。II-D 冻结首步风险消除，同根重采获严格胜局，Hammer Time 回归通过。全量验收基线仍为 II-H.9.1。 [报告与复现](m1-nosl3c-iii2-hibernate.md)

- II-I.1 定向候选 `0.51.5-iii.1` 已补齐 Hammer Time，普通与升级效果、两条冻结前缀及 Forge 正负例通过。II-C 原 Bulwark 风险仍在。同根重采一条严格败局，另一条因终局 Power 差异拒绝。II-H.9.1 保持为最近全量验收。 [报告与复现](m1-nosl3c-iii1-hammer-time.md)

- II-H.9 候选集成验收在 `0.51.5-iih.8.1` 和 II-H.7 Headless 上得到冻结 42/65、独立 11/16 和 45/60，v4 冷跑与恢复一致。II-H.9.1 修正常规宿主的部署路径，原六项失败均通过，完整主测试 164 通过、1 跳过，完成全量验收。 [报告与复现](m1-nosl3c-iih9-integration.md)

- II-H.8 隔离构建 `0.51.5-iih.8.1` 继承 II-H.4–H.7，复用 II-H.7 Headless。玩家回合准备先完成 Tyranny 选择及耗尽，再触发 Furnace。Sovereign Blade 的 29 个历史动作全部与原生精确对齐，牌区及实例正负例、四条历史回归和 Void Form 对照均通过。 [定向证据与复现](m1-nosl3c-iih8-sovereign-blade.md)

- II-H.7 隔离构建 `0.51.5-iih.7.1` 继承 II-H.4–H.6。Headless 合法菜单使用原生 `CanPlay` 和经战斗钩子修饰的固定星费。Hunter Killer 历史败局、Void Form 星费正负例及三条历史回归均通过。 [定向证据与复现](m1-nosl3c-iih7-hunter-killer.md)

- II-H.6 隔离构建 `0.51.5-iih.6.1` 继承 II-H.4 与 II-H.5。共享死亡清理按原生战斗监听器作用域应用幻影 Power 的移除条件。Fogmog 历史败局、免费攻击生命周期正负例及两条历史回归均通过。 [定向证据与复现](m1-nosl3c-iih6-fogmog.md)

- II-H.5 隔离构建 `0.51.5-iih.5.1` 继承 II-H.4.1。Gas Bomb 致死攻击后会先完成普通自杀和共享死亡清理，再发布败局。Living Fog 历史败局、召唤物原生正负例和吞噬暗影／Flutter 历史胜局均通过。 [定向证据与复现](m1-nosl3c-iih5-living-fog.md)

- II-H.4 隔离构建 `0.51.5-iih.4.1` 先同步伤害钩子的 Power 层数，再做共享死亡清理，并对齐吞噬暗影的终止条件。历史 II-E `2:000001` 已获精确胜局。[定向证据与复现](m1-nosl3c-iih4-shared-combat.md)

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
$s = 'logs/m1-nosl3c-iih8-final'
$h = 'experiments/m1-nosl3c-iih9'
$l = @('logs/nosl3c-iic-random-final','logs/nosl3c-iid-release-independent','logs/nosl3c-iie-broad')
python "$h/run.py" replay logs/new-iih91-probe @l --solver $s --workers 1 --case nosl3c-iic-random-final:0:6
```

主要证据见 [H.3 证据](../experiments/m1-nosl3c-iih3/evidence.json)、[II-H.2 证据](../experiments/m1-nosl3c-iih/duration-evidence.json) 和 [语义收敛报告](m1-nosl3c-solver-semantic-convergence.md)。

## 额度节约

- 先读本文和当期报告，再查看相关源码。优先用 `rg`，限制搜索到需要的源码目录，不递归扫描整个 `logs/`。
- 大日志仅读失败摘要和相关尾部。用只读查询从 JSON、SQLite 提取根、阶段、分类及哈希，不将完整内容输出到上下文。
- 先定向测试，再在里程碑做全量验收。保留已确认实验的版本和证据，避免每次修改都全量复跑。
- 将大型原生套件分批执行。失败时记录首个异常、命令阶段、宿主日志路径和退出码。重试必须保留首次结果。
