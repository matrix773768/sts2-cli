# Codex 交接

## 当前基线

- 仓库 `matrix773768/sts2-cli`，分支 `port/v0.113.1`。每次启动先执行 `git status -sb` 和 `git rev-parse HEAD`。稳定化起点为 `5043f95467ee88a9e41375c51278a651b93ad14d`。
- STS2 v0.113.1 Build 26660232，CoreCLR **9.0.7**。II-J.5A 与 II-J.5B 均已通过，II-J 正式关闭。正式全量验收基线为 Solver **0.51.5-iij.4**，配套 II-H.7 战斗宿主与 II-H.9.1 常规 Headless。
- 全量验收构建的 Solver DLL SHA-256 为 `2c7a9ec1d0f6a58226be9aee9230268b40ab96fa6efe582cddf2e376b9a18e5f`。
- II-H.7 战斗宿主 SHA-256 为 `b3f8ce1d862bdb98000bfeb90d701239e50be17034739c5c2ed18e26716150f0`。常规 Headless 部署至 `logs/iih9-main-host/bin/Debug/net9.0`。
- E3 战斗认证 `sts2.nosl.iih3.enemy-side-exact-combat.v1`。保留 II-G Completion 死亡等价合同 `sts2.nosl.iig.completion.enemy-death-window.v1`。

## 工程状态

- II-K.1 候选 `0.51.5-iik.1` 修复预测奥斯蒂跨回合攻击计数。pair16 `0:000009` 原差异边界精确匹配，同根重采获严格胜局。 [定向验收](m1-nosl3c-iik1-rattle.md)

- II-J.5B 保留冻结 42/65 的严格认证及终局戳，风险同根重采 8/8，固定套件 12/16 与 52/60，v4 冷跑与恢复一致，主测试 164 通过、1 跳过。 [全量验收](m1-nosl3c-iij5b-integration.md) · [II-J.5A 定向验收](m1-nosl3c-iij5a-targeted-acceptance.md)

- 历史正式基线为 Solver `0.51.5-iii.8`（II-I.9B）。 [历史验收](m1-nosl3c-iii9b-integration.md) · [项目状态与历史证据](PROJECT_STATUS.md)

- 奖励和地图处置由独立原生流程负责。战斗审计的私有字段不进入 Actor。 [II-H.3 稳定化报告](m1-nosl3c-iih3-stabilization.md)

## 保留数据

- `logs/nosl3c-iic-random-final`、`logs/nosl3c-iid-release-independent`、`logs/nosl3c-iie-broad` 三份冻结账本。
- `logs/m1-nosl3c-iih2-candidate`、`logs/m1-nosl3c-iih-reward-build`、`logs/m0-v5/dotnet9` 和 `lib`。
- II-H.3 审计、原生宿主失败目录、唯一模型检查点和 SQLite 训练事务账本均保留。不要重用旧输出目录。历史实验文件的删、移、压缩或清理需单独授权。 [存储审计](local-storage-audit.md)

## 额度节约

- 先读本文和当期报告，再查看相关源码。优先用 `rg`，限制搜索到需要的源码目录，不递归扫描整个 `logs/`。
- 大日志仅读失败摘要和相关尾部。用只读查询从 JSON、SQLite 提取根、阶段、分类及哈希，不将完整内容输出到上下文。
- 先定向测试，仅在重大里程碑做全量集成验收。保留已确认实验的版本和证据，避免每次修改都全量复跑。
- II-J.5B 首轮跨套件并发导致宿主超时，分阶段串行复验通过。后续大型验收默认分阶段串行调度。失败时记录首个异常、命令阶段、宿主日志路径和退出码。重试必须保留首次结果。
