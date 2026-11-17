# STS2 AI — 项目状态与交接（PROJECT_STATUS）

> 更新日期：2026-11-17（Asia/Singapore）
> 当前阶段：M0 完成主要验证，准备 M1-A 搜索环境接口设计。
> 本文件描述 **matrix773768/sts2-cli** 的 `port/v0.113.1` 分支，不代表上游 `wuhao21/sts2-cli` 或 `main` 的支持情况。
> 基线代码提交（更新本文档之前）：`bc48ac58aeca80c2c7b9249cbf98f316ae99a27b` — Restore native Ancient healing and act-start travel rules。
> 本文件是交接摘要；具体实现、测试断言、原生 IL 及日志以当前仓库和本机实际文件为准。不要将历史总结当成新的测试结果。

## 1. 项目目标与工作边界

长期目标：在允许 Save/Load（SL）的规则下，利用忠实于原生《杀戮尖塔 2》的无画面模拟器，组合模拟、搜索与学习，提高直至争取超越顶尖人类玩家的通关胜率。

研究重点首先是**局外决策**：地图路径、卡牌奖励、事件、商店、休息点、资源分配等。战斗暂以现有原生引擎和简单策略执行；计划后续评估、接入 [Torch1230/CombatSolver](https://github.com/Torch1230/CombatSolver)，**目前未集成**。短期目标不是训练模型，也不是追求测试策略高胜率，而是建立可靠的 SL 分支接口与可重复的性能基准。

当前分工：本 ChatGPT 项目对话负责方案、审查和阶段验收；本地 Codex 负责源码、构建和实测；GitHub Desktop 可用于人工推送。各 Codex 主阶段建议开新对话，先读本文件与 `CLAUDE.md`，再检查 Git 状态。

## 2. 仓库、分支、环境

- 仓库：[matrix773768/sts2-cli](https://github.com/matrix773768/sts2-cli)；开发分支：`port/v0.113.1`；不要修改或合并 `main`，除非另行明确决定。
- 游戏：Steam Windows x86_64 测试版 **v0.113.1 / Build ID 26660232**。具体安装路径由本地环境确定；绝不写入 Steam 原件。
- .NET：SDK **10.0.404** 可以用于构建；**headless 引擎运行必须使用兼容的 CoreCLR 9**，此前在隔离环境实测为 **9.0.7**。Harmony 2.4.2 在测试的 CoreCLR 10.0.15 环境中触发不支持错误。
- 运行入口：`python/headless_runtime.py` 的 `headless_command()`。可使用 `STS2_DOTNET` 指定含 .NET 9 的 dotnet host，`STS2_DOTNET_VERSION=9.0.7` 固定版本；实际版本应与本地已安装运行时匹配。目标为 `src/Sts2Headless/bin/Debug/net9.0/Sts2Headless.dll`。
- 原生 DLL 来自用户合法安装的 Steam 游戏并放入本地忽略的 `lib/`；**不上传**游戏 DLL、运行时、Steam 文件、用户数据、存档、日志。当前分支通过运行时 Harmony 补丁处理无画面行为；**不要执行上游 README/setup.sh 所述的离线 IL 补丁流程**，除非单独研究并获批准。
- 本项目的 Windows 实测优先于仓库通用 README/CLAUDE.md 中针对上游 v0.111.0、macOS 或其他环境的历史说明；不要因此忽略 `CLAUDE.md` 的通用开发约定。切换游戏版本必须重新核验 API、Harmony 补丁及回归。
- 常用路径：`src/Sts2Headless/RunSimulator.cs`（生命周期、状态、动作）；`src/Sts2Headless/Program.cs`（JSON 协议）；`tests/conftest.py`（隔离游戏进程）；`tests/run_route_smoke.py`（真实路线冒烟）；`python/play_full_run.py`（旧简易批量玩家，不宜直接作为严格验收器）。

## 3. M0 已完成里程碑（按主要证据）

| 阶段 | 已证实的能力 / 结论 | 主要证据 |
| --- | --- | --- |
| M0-V3/V4 | 适配 v0.113.1，原生未离线修改 DLL 的 Neow→地图→战斗冒烟成功。 | `RunSimulator.cs` 及原始冒烟记录 |
| M0-A1 | 初始/Neow 后地图恢复、单房间连续运行与独立进程完整 JSON 重放、独立 A/B/A。 | `tests/test_save_load.py` |
| M0-A2 | 第一战后中期地图检查点，经下一战与领奖的跨进程重放一致；该检查点只有一个合法后续节点，A/B/A 按条件跳过。 | `tests/test_save_load_cross_room.py` |
| M0-V5 | CoreCLR 9.0.7 下 Harmony 四类补丁有真实触发证据；`Cmd.Wait`、`TalkCmd.Play`、`Task.Yield` 代表场景运行正常；本地化仅部分分支实测。 | M0-V5c 诊断日志；`python/headless_runtime.py` |
| M0-C1 | Ironclad A0，三个固定种子沿真实地图到原生正常死亡（Act 1 第 5/7/11 层），另各复跑一次，共六次无模拟器故障或超时。 | `tests/run_route_smoke.py` |
| M0-C2/C2b | 发现并修复读档后 `EnterAct` 重置未知节点概率、无画面商店退出未清理同步器/历史、删牌售罄仍显示报价。连续两店、购买/重复购买、存档重放有回归。 | `tests/test_merchant_lifecycle.py`；`tests/ShopStateProbe/` |
| M0-C3 | 真实路线 `run_1` 击败 Act 1 The Kin，领取 Offering，进入 Act 2 Hive；第二幕地图与 RNG/odds 重放及 A/B/A 经实测。 | M0-C3 真实路线及分支日志 |
| M0-C3b | Boss 卡牌奖励未完成时拒绝通过 `proceed`、`leave_room`、地图动作等提前切幕；统一由战后结算触发跨幕。 | `tests/test_boss_reward_gate.py`；`tests/boss_reward_run_1.jsonl` |
| M0-C3c | 原生 Ancient 事件触发幕间治疗，修复提前直接改 HP；Ancient 是后续幕必经起点。真实 A0 从 8/93 进入 Orobas 后治疗 85、历史同步记录 85；定向构造 A2 按原生截断治疗 67；新 S2 重放与 Ancient 后 A/B/A 成功。 | `tests/test_ancient_healing.py` |

最后一次 M0-C3c 本地报告：**44 passed、1 skipped、0 failed、0 timeout**（本机执行；本文件不声称 CI 或本环境重跑）。部分阶段曾分别报告 50/52 项通过，测试集合和命令不完全相同，**不可直接比较总数**。此后每次修改需记录实际执行的测试范围与具体跳过原因。

当前开发分支已包含 M0-C3c 提交 `bc48ac5`。不要把 M0-C3c 之前的旧 S2 当成治疗行为的新基准：旧存档保留原先已提前补满的 HP，兼容加载不代表可自动补齐历史。

## 4. 当前能力边界与不变量

**已支持且有实际证据：** 从合法地图检查点保存、独立进程加载、同一命令序列完整响应/地图重放；多个已测试场景的原生序列化 RNG、unknown-node odds 和地图历史一致；在不可变源检查点上做 A/B/A；真实路线进入第二幕及原生 Ancient 治疗；商店实际购买与删牌状态恢复。

**尚未承诺：** 任意时刻精准 `clone()`。当前 `RunSimulator.SaveCheckpoint()` 在 `MapRoom` 中可保存当前状态；在非地图房间会产生**进房前回退检查点**，并非当前战斗、商店、奖励或事件进行中的精确状态。M1 API 不得把它包装成任意决策可复制。需要显式检查和拒绝不安全位置（不应自动转换并声称精确恢复）。

**正确性不变量：**
1. 相同原生存档、游戏/引擎版本与动作序列，所覆盖路径须逐步一致；不仅对比初始 JSON，也比较后续响应、完整地图，适时比较原生 RNG、odds、历史。
2. A/B/A 从同一份不可变源检查点、独立进程运行；源文件字节和 SHA-256 始终不变。
3. 正常死亡 `game_over(victory=false)` 是有效游戏终局，不是模拟器故障；策略无法处理、非法动作、原生错误、通信错误、超时必须分类报告。
4. 所有真实路线测试只使用合法地图动作；`enter_room`、`set_player` 等辅助构造必须单独标明，不能冒充真实跑局。
5. 不擅自修改已有 M0 测试断言、固定种子或历史期望来掩盖回归。
6. 所有外部资源与存档、日志隔离；设置启动、逐命令、整局超时并清理子进程。

## 5. 已知风险与未覆盖范围

- M0-C3c 的 A2 取整验证来自**隔离构造的 S2**，并非完整 A2 真实跑局；A2 高难度真实路线仍待覆盖。
- 第三幕与最终 Boss、不同角色和多种特殊遭遇尚未完成本项目的系统性回归。
- Ancient 事件中途、Boss 奖励待决等非地图状态的精确存档恢复尚未验证；当前保存语义对此明确不支持。
- CoreCLR9 Harmony 的所有重载/本地化分支尚未逐条覆盖；Windows 实测不能泛化为 Linux/macOS。
- 独立进程读取存档的单次约 1.8s 结果含初始化影响，不能直接估算批量搜索吞吐量；需要冷/热、端到端和并行 benchmark。
- 当前 `README.md` / `CLAUDE.md` 尚包含上游环境和离线补丁描述。不要在无审查情况下照搬其兼容性声明。未来可单独更新文档。
- Torch1230/CombatSolver 尚未集成，接口兼容性未验证；当前没有学习算法或通关胜率基准。

## 6. M1 方向与首个任务

**M1-A（下一步；先架构调查/设计，不直接开发大规模系统）：**
- 设计 `reset / observe / legal_actions / step / save_checkpoint / branch / rollout / close` 最小 Python API，定义入参、输出、错误类型与生命周期；承认现有 JSON 协议未必完整枚举所有合法动作。
- 明确区分可观察 JSON、原生序列化状态、**已验证的地图检查点**、不能精确复制的房间内决策状态。
- 设计 checkpoint 元数据：游戏 build、适配器 commit、运行时、角色/seed、Act/坐标、存档 SHA-256、协议版本、来源与合法复制边界。
- 设计 A/B/A、逐步重放和无副作用检查，以及确定性、非法动作/超时/错误分类。
- 设计可复现性能基准：启动、`start_run`、`load_save`、普通动作/战斗、独立分支端到端、顺序/少量并行吞吐量、P50/P95、峰值内存、失败率；区分冷启动与热启动。
- 比较每分支新进程、常驻进程重复加载、进程池与未来内存克隆的正确性/污染/复杂度及成本。不预先假设常驻进程安全。
- 设计与 CombatSolver 的未来接口边界，但不开始集成或训练。

**M1-B（待 M1-A 审查后决定）：** 从不可变地图检查点创建独立进程分支的最小原型，沿已测试路线验证完整结果并提供 benchmark。保持战斗策略为可替换后端；先正确性再性能。

## 7. 协作与操作流程

- 新 Codex 对话开头：阅读本文件、`CLAUDE.md` 与实际代码；确认当前 Git 分支、HEAD、工作区状态、Steam build、CoreCLR；优先报告与本文档不一致之处。本文档不是代替代码审查或测试的权威来源。
- 每项任务按「明确目标 → 证据/失败回归 → 最小修改 → 定向与全量回归 → diff 审查 → 报告」进行；阶段结束更新本文件的 HEAD、结果与风险。
- 先保留本地日志及可复现命令，再决定是否进入正式测试源码。严禁将个人本地绝对路径、密钥、Steam DLL、运行时、存档或日志提交到仓库。
- 默认不修改 `main`，不自动合并或开 PR；Codex 在用户明确要求时提交。Windows Git CLI 可能出现 Schannel `SEC_E_UNTRUSTED_ROOT`：最多正常尝试推送一次，失败后交由 GitHub Desktop 手动推送；**不要关闭 SSL 校验**。
- 除非任务需要，不重复调查已经有实证和回归的 M0 功能；若新证据与既有结论冲突，及时更新状态与测试。

## 8. 新对话最短交接提示

> 这是 STS2 AI 项目的 `matrix773768/sts2-cli` 仓库，开发分支 `port/v0.113.1`。请先阅读 `docs/PROJECT_STATUS.md` 和 `CLAUDE.md`，核对 Git HEAD、工作区和本机游戏/.NET 环境。M0 已完成主要兼容性、地图 SL 重放、商店、Boss 奖励与原生 Ancient 治疗回归。当前进入 M1-A：**只做搜索环境 API、检查点语义和性能基准架构设计**，暂不编写搜索算法或修改游戏逻辑。若文档与源码有冲突，以实际代码与新测试证据为准，报告差异。
