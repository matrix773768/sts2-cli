# HK0 — CombatSolver 1.0.2 / HotKernel v2 技术调查

2026-11-25。上游冻结提交 `131d10ae4499b56332787af61fe4a9306e65860f`，本项目调查起点 `port/v0.113.1@2ad35f6`。正式基线使用 CombatSolver `0.51.5-iik.3b`、II-K.4B 战斗宿主、常规 Headless、STS2 0.113.1 Build 26660232 与 CoreCLR 9.0.7。[上游冻结提交](https://github.com/Torch1230/CombatSolver/commit/131d10ae4499b56332787af61fe4a9306e65860f) · [本项目冻结基线](m1-nosl3c-iik5-integration.md)

**优先推进 A，用上游离线宿主适配 DC3A Oracle。** 本地 DOP=1 已取得两回合真实原版胜路和同场原生部署证据。正式参考仍需证明根同一性和从独立冷启动逐步重放的终局一致性。**B 可以独立于 HotSearch 做成模拟后端**，模型可沿用公开输入协议，工作量主要在投影、随机边界、选牌和认证。**C 暂缓**，上游已移除本项目宿主绑定的旧模拟、选牌和搜索类型。

## 上游构建、发行与性能证据

- 已下载 `CombatSolver-1.0.2.zip`，SHA-256 与公开资产页的 `58bab294eae0c5efba1ac7cce882e29ef19a4579de60785a913599b383f47588` 一致。CRC 检查通过，含 manifest、DLL 和两份许可。发行 DLL SHA-256 为 `7840c6ae099252d71a535fb64c74e1d086f2b713489eb6d13d983dcb9ebbcc4c`。发布说明覆盖单人 Standard、Dread、Blitz 的 0.113.1，并声明兼容 0.113.0。包内 manifest 为 1.0.2，游戏最低 0.113.0，依赖 RitsuLib ≥0.6.11。离线宿主从源码另建。[发行说明](https://github.com/Torch1230/CombatSolver/releases/tag/v1.0.2) · [包与摘要](https://github.com/Torch1230/CombatSolver/releases/expanded_assets/v1.0.2)
- Solver 用 Godot.NET.Sdk 4.5.1、C# 13、`net9.0`、Krafs.Publicizer 2.3.0，引用 `sts2.dll`、Harmony、GodotSharp、RitsuLib。Harness 用常规 .NET SDK、同版 Publicizer 及 Solver 的 `InternalsVisibleTo("OfflineSearchHarness")`。本地用 SDK 10.0.404 编译 `net9.0`，用项目保留的 CoreCLR 9.0.7 运行，Steam 游戏 DLL 与原冻结哈希 `62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3` 一致。Workshop manifest 为 RitsuLib 0.6.15，选择包内 `0.113.0` 兼容目标及 shared。构建始终使用 `CopyModOnBuild=false`。[Solver 构建](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/CombatSolver.csproj) · [Harness 构建](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/tools/search/OfflineSearchHarness/OfflineSearchHarness.csproj)

| 上游证据 | 结果与口径 |
| --- | --- |
| [1.0.0 测试卷 33](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/docs/archive/testing/volume-33.md) | Phase 7B 对 Phase 0。4 根 Evaluate DOP=1，86.09 → 3.21 s，26.81×。6 根 Coordinator DOP=8，277.15 → 5.26 s，52.70×。两组各自对旧阶段，根集、入口和并行度不同。 |
| [1.0.2 测试卷 35](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/docs/archive/testing/volume-35.md) | 行为证据基于 Wave 4 `a9334fc2`，发行提交收口版本与资料。Gate C 1,945,775 trans/s、0.0 B/step，测同一根的 Unpack、PlayCard、Pack、Hash。2,600 场差分和 400 场部署来自离线宿主。170 根 1.0.2 对 1.0.1 对照总耗时降 19.0%，胜局仍为 164/170，各有一局转胜和转败。41 根 holdout 平均 V 降 0.51。 |

开发卷 33 记录旧栈退役和热核上线，卷 34 记录成长及遗物策略恢复、隐式选牌与触发时机，卷 35 记录搜索分期保路、死循环和战斗语义修复。本地 HK0 无旧冻结宿主的配对测速，也无正式吞吐或胜率估计。上游 V 包含资源与药水权衡，DC3A 独立核算战斗净损。[开发卷 33](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/docs/archive/development/volume-33.md) · [开发卷 34](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/docs/archive/development/volume-34.md) · [开发卷 35](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/docs/archive/development/volume-35.md)

## HotKernel 独立作为模拟后端

| 接口 | 冻结源码及接入要求 |
| --- | --- |
| 原生根 | `HotRootBuilder.BuildFromLive(CombatState)` 在主线程稳定边界读 `LocalContext` 玩家、牌堆、历史、怪物、Power 和 RNG，产出 `HotRootBundle(HotRules, CombatHotState, HotColdSidecar?)`。`CombatRootSnapshot.CaptureHotRoot` 增加续用戳。Builder 注释提及 detached snapshot，实际可见的 Builder 入口只有 `BuildFromLive`。配方须先变成原生 `CombatState`。Vanilla gate 对外来模型显式报错。 |
| 完整状态 | `CombatHotState` 共 17,256 B，固定核心 1,128 B，含玩家、Osty、Wuppy、回合和阶段、阵容、终局、资源、历史、十条 RNG、药水、球、箭及牌区长度。四段容量区上限为 16 敌、96 Power、64 遗物状态、256 牌，牌依 Hand／Draw／Discard／Exhaust／Play 排列。牌含 UID、定义 ID、升级、关键字、费用、附着和动态量。规则目录含定义、怪物图、牌池、根元数据；Cold 管理脱离牌、十进制变量、费用溢出、Rupture、Dampen 与怪物日志溢出。 |
| 合法动作与一步 | 架构文档中的 `HotSimulator` 和 `HotActionGenerator` 实际落在 `HotCombatEngine`。`EnumerateLegalActions(in state, cold, rules, Span<HotAction>, includePotions)` 枚举带手牌索引、敌槽、可选药水的动作与 EndTurn，必要时仅返回 TurnSetup。缓冲须足额。`Step(ref state, ref cold, rules, scratch, action, choices)` 原地执行，返回 `Executed/NeedsChoice/Outcome`。一次 Step 可覆盖自动牌、多段触发和回合结算。 |
| 交互与独立分支 | 稳定父状态值复制，规则只读共享，Cold 按 COW 使用，每 lane 独立 `HotExecScratch`。待选时工作副本可能已部分执行。保留动作前快照与已确认选择，再用同动作和选择序列重执行。热搜可对等价候选保留代表元；模型菜单须维持公开实例身份和顺序。 |
| Pack、Hash 与审计 | `HotStatePacker.Pack` 只打包活跃段，默认规范化会修改传入值和 Cold 引用，包括 UID 重编号及 padding。先复制再打包，单独保持交互实例映射。`Unpack` 恢复值区，规则与 Cold 须随快照保留。`HotHash.ComputeHash` 覆盖 packed bytes 和 Cold；转置表还比字节和 Cold 结构。搜索键适用同一规则与版本，原生续用戳和 DC3A 持久根指纹各自核验。 |
| RNG 与条件世界 | 保存九条 run 流与玩家 NonCombatGeneration，单流含四个 64 位状态字及计数。可重演完整世界、独立复制分支，也有 `CreateFromSeed`、`Advance` 和抽样原语。条件世界需要由宿主依据公开历史采样未知牌序、敌方可达状态及 RNG，保留已知牌顶／牌底和实例绑定。只换 RNG 仍保留真实未知牌序，也不会自动满足历史约束。上游无此公开条件采样接口。 |
| 终局、持久资源、长战 | 结果分 Ongoing、Victory、Defeat、EventDefeat；敌人另有复活与永久死亡阶段。HP、MaxHP、回合计数为 int，终局回合字段饱和于 255。状态含救命回血、药水、金币／被盗资源、成长、至亮之焰最大生命消耗。`ComputePostCombatRelicHeal` 将胜后回血单独计算。应分别记录锁定 HP、战后 HP、最大生命、伤害、回复、药水及成长。HotSearch 通常限 28 回合，Boss 可到 40，每回合动作限 64。独立热核仍受牌、Power、敌人及单动作 24 个选择槽等容量限制。 |

实际接入可先使用窄 C# 适配层和内部友元机制。核心步进无需 HotSearch，原生导入仍有游戏与规则依赖。未发现单独发布的 HotKernel DLL 或稳定公开 ABI。[架构地图](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/docs/ARCHITECTURE.md) · [原生导入](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/src/HotKernel/Import/HotRootBuilder.cs) · [状态及打包](https://github.com/Torch1230/CombatSolver/tree/131d10ae4499b56332787af61fe4a9306e65860f/src/HotKernel/State) · [步进与动作枚举](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/src/HotKernel/Sim/HotCombatEngine.cs)

### NOSL 与模型接口

模型入口应沿用本项目公开 schema 的白名单，含可见资源、手牌、敌人意图、选择、合法动作索引与历史。Python 编码器、动作条件模型和 batch 推断可沿用，前提是同一公开历史逐步生成相同 wire 并校对执行索引。原生戳、完整牌堆、RNG、藏在私有计数中的未来信息、搜索语义键、内部评分与 Oracle 路线留在宿主私有审计域。

确定性搜索在首次读取未知牌、随机目标、生成、随机费用或有多个可达结果的怪物分支前停住。有序牌堆可以在 RNG counter 无变化时泄露信息。先用真 RNG 和隐藏牌序选路线，再清理输出字段，仍会泄露给所选动作。条件采样使用公开信息和独立种子，兄弟动作共享采样批、各自复制，用相同后续行为和预算聚合。模型只读各假想世界中已经揭露的观测。验收用公开历史相同、私有顺序／RNG 不同的两根，使公开菜单、可见终点、分数及首动作一致，并用 Oracle 对照确认私有差异能被测到。[SV1 随机边界与公平验证](m1-sv1-turn-state-graph.md) · [模型和搜索设计](m1-sv-architecture.md) · [现有推断入口](../experiments/m1-sv4a/loop_policy.py)

## HotSearch 与 DC3A

- `SolveSingleBeam` 对应 Evaluate，`Solve` 对应 Coordinator。后者分配 Stage 1/2/3、药水档及 Offense／Rescue，使用冻结的 `SearchPolicySnapshot`。束宽、分支、DOP、展开节点与软时间可配。过期在批次边界检查。DC3A 的 128/512/2,048 预算是转移数，需要显式计数或重新校准、冻结新版阶梯。
- Coordinator 用 incumbent 剪枝并在阶段间比较候选。arena 清空前会物化并保留最佳项。已有胜路后可继续减损，也受药水、救命、长期资源和达标早停政策影响。TimeLimit/NodeLimit 可以伴随可执行胜路。部分阶段提供初步回调，现成 CLI 只交付整次结果。DC3A 应跨档保留已原生验证的最小净损胜路，同时记录上游评分、搜索边界、首胜发现时间或明确的返回时间。
- Coordinator 和并行展开器支持协作式 `CancellationToken`，默认 Harness 两条搜索入口传 `CancellationToken.None`。软时限以外仍有初始化、物化及复放开销。DC3A 接入独立进程硬时限，若增加中间候选输出和协作取消，只持久化通过验证的候选，分别保留超时、取消、无胜路与原生差异。
- `HotPlanMaterializer` 用同一热核重走轨迹，输出实例语义键、目标 CombatId、选牌、回合计划及续用戳。普通 M2 产出结果，原生验证可用 `RealCombatDriver`、`--soak-deploy`、`--replay-bundle --lockstep-actions --deploy` 或游戏内 Headless。DC3A 需同根冷启动，把选定路线逐步交原生驱动并复查公开状态、选择、阶段、终局和锁定 HP。
- Harness 在普通 .NET 中启动真实游戏模型，绕过部分 Godot、I/O、本地化，RitsuLib 运行初始化未执行。普通 `--request` 可建新跑局／夹具，新版另有若干 bundle 回放入口。DC3A 私有配方仍需适配。部分离线手册参数来自旧栈，以冻结版代码为准。II-K.4B 的 Godot ABI／信号与项目 E3 认证须独立验证。[离线手册](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/docs/OFFLINE_SEARCH_HARNESS.md) · [Headless 手册](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/docs/HEADLESS_TESTING.md) · [HotSearch](https://github.com/Torch1230/CombatSolver/tree/131d10ae4499b56332787af61fe4a9306e65860f/src/HotSearch) · [DC3A 阶段 A](m1-dc3a-solver-reference.md)

## 本项目接口影响

| 接口 | 迁移工作 |
| --- | --- |
| 原生根构建 | 中。复用 PRE0B `pre0_start` 配方与初始化顺序。在新宿主生成原生根，核对私有牌实例、RNG、资源及公开开局。 |
| 战斗预测和执行 | 高。旧 `CombatPredictionSimulator`、`SimulatedCombatState`、`InteractiveCombat` 类型和反射入口消失。保持 Python 步进协议，新增 C# 步进、续选重演、失败分类与原生执行适配。 |
| 公开状态和模型特征 | 中到高。移植 PRE0B 投影、已知牌跟踪、选择和动作索引。逐项对齐费用、意图、Power、牌序、合法掩码，核对现有模型在相同特征上的推断。 |
| NOSL 经验生产 | 高。保持公开观察、动作、行为 logp、奖励与预测／原生身份，保留截断及 unsupported。恢复前缀逐项对齐公开观察、选择、动作和私有审计戳。 |
| SV1 确定性回合图 | 高。将读未知牌及 RNG 探针接入热核触发源，保留 Turn A/B 稳定边界、全部入边、首动作可达集合及预算计数。按独立语义证据收紧等价键。 |
| 公平信息搜索 | 高。沿用 SV4A 的公开图和私有键隔离，先验收确定性边界，再接条件世界。对私有根变体检查排序、得分、前沿和动作不变。 |
| 反事实动作分支 | 中到高。值复制简化同根分叉，选择叙述、重放和共同后续行为仍需适配。保持同世界配对，区分 Oracle 全状态反事实与 NOSL 条件世界反事实，并验证分支隔离。 |
| INF1 批量任务 | A 低到中，B/C 高。独立模板锁定产物与运行时哈希、清单、预算、资源和每根事务。冷跑与恢复对照，取消保留已提交行与退出分类。 |

[PRE0B](m1-pre0b-throughput-and-coverage.md) · [SV1](m1-sv1-turn-state-graph.md) · [DC3A 协议](m1-dc3a-task.md) · [INF1 管理器](inf1-training-manager.md)

### II-J 与 II-K 语义对照

下表是静态核对，本轮 Ironclad 冒烟未覆盖这些专项。接入验收使用开发用最小原生夹具，现有封存集须另行批准。

| 原合同 | 上游对应与差异 |
| --- | --- |
| II-J.1 Quasar 与实例选择 | Quasar 用 GeneratedCard 来源，带候选索引与定义 ID；已有牌区以 UID 对应，物化与 `NativeChoiceRuntime` 有 StateKey、来源和降级匹配。复核普通／升级、空选、候选顺序及重复实例出现次序。 |
| II-J.2 Guards | 热核把 `min(HandCount,24)` 写入待选描述，项目公开合同是原生声明的 999999999。公开适配需独立保留声明与可执行数量，再测空选、单选、全选。 |
| II-J.3 Hidden Daggers | 有候选数不超过要求时按手牌顺序隐式全弃及更多候选时显式多选。生成按动态变量并带升级标记，需复跑普通／升级各 0–3 候选的选择与 Shiv 状态。 |
| II-J.4 Pale Blue Dot | 有出牌后钩子与根导入的已激活标记。钩子调用 `ApplyPowerById`，共用写入检查受体存活，未找到等价的原生 `IsEnding` 守卫。末敌致死时玩家仍存活，延迟抽牌 Power 与已激活标记属于高优先级差分。 |
| II-K.1 Rattle | 历史补种 `OstyAttacksThisTurn`，攻击累加，回合代码重置。Rattle 命中与预览均读取计数。复核跨回合开局顺序。 |
| II-K.2.1／.2 球体终局与 Lightning Rod | Step 与球体阶段有终局检查，Lightning Rod 挤球后在 ending 直接返回，非终局继续减层。分别核对胜利阶段、续体戳与两种层数。 |
| II-K.2.3 Glass Orb | 单个 Glass passive 先衰减自身基础值再伤害。外围遍历遇到 ending 提前结束，末敌被前序球杀死时后续 Glass 的同批衰减仍有可疑差分。 |
| II-K.2.4 Fossil Stalker | Suck 合计有效命中后按施加者存活加 Strength，逻辑位于玩家死亡返回之前。共用写入检查受体存活，未找到等价的 `IsEnding` 守卫。用 1 HP 致死与高 HP 未死两夹具优先验证 Strength 和终局。 |
| II-K.3B Sneaky、One for All、Tank、Blade Symphony | Sneaky／Tank 有自身 Power 的目录操作；One for All、Blade Symphony 可查到卡定义。目录声明不足以确认零费／X／自动出牌伤害、Guarded、格挡或 Shiv 顺序；重新跑 3B 的九个单人夹具，显式记录卡池排除与缺失执行分支。 |
| II-K.4B Rolling Boulder | 有私有字段导入、出牌和回合开始效果。旧修复在 Headless 的 Godot ABI 和信号，独立验证包括真实伤害边界和进入 Play。 |

[II-J 累计验收](m1-nosl3c-iij5a-targeted-acceptance.md) · [II-K 累计验收](m1-nosl3c-iik5-integration.md) · [冻结热核](https://github.com/Torch1230/CombatSolver/tree/131d10ae4499b56332787af61fe4a9306e65860f/src/HotKernel)

## 本地有限真实验证

SQLite `mode=ro` 查到 `dc2b-night1-hf1-r1` 为 `running`、stage 3（G3 Search），有未结束 run。构建用单 MSBuild worker 和非共享编译；冒烟串行、显式 DOP=1，设置 `DOTNET_PROCESSOR_COUNT=1`，从 BelowNormal shell 启动。未开启 B2 多线程、全量 fuzz／soak、正式训练、正式 DC3A 计算或封存确认集。

| 检查 | 本地结果 |
| --- | --- |
| Release 构建 | Solver 40.15 s，Harness 28.98 s，均 0 警告／0 错误。源码 ZIP SHA-256 `3aa49546ccf0bad704c2cfd77182a9d311d88622196cbdece9a7a1e9c51199b3`。实测 Solver DLL `48d23255a887d86a38bf2973de954500a3ee5c185e2c3b8275dc6050d4e47a06`，Harness DLL `5ac4e86df8ca5ae8a1c123c7e549b3f5e9fa9e9d7668aa01196223b970772076`。 |
| 布局与 RNG | 7/7。2,808 B 样本逐字节翻转检测、Pack 往返、Cold 结构差异检测、1,000 次 RNG 取样及洗牌与本机 STS2 bit-exact。 |
| 原生根、动作、复制与重复执行 | Gate A 19/19 原生根及 Pack/Unpack。Gate B1 六角色 246 步，合法动作枚举、步进、往返及从原根确定重演通过。B1 覆盖模拟自洽。 |
| 80／160／999 HP | 同一 Ironclad 流程建原生根，分别注入 80/80、160/160、999/999，敌人 15/55 HP，开局三张 Strike。三档均回读指定 HP，捕获 13 张牌，6 展开／15 转移得到三个 Strike 的完整预测胜路，终局 HP 保留，预测损失 0。此项覆盖高 HP 导入及短路径。999 HP 长战尚未验证。 |
| Ironclad 整场胜路及原生部署 | A10 Standard `RUBY_RAIDERS_NORMAL`，seed 7777 生成序列第 0 场，起始 76/85。Coordinator 一次求解，645 展开／4,170 转移，509.94 ms，边界 `TimeLimit`。真实游戏程序集部署 2 回合，跨回合复用 1 次，0 次意外重算、选择差异或硬错误，胜利、战后 82/85 HP、0 药水。同场部署通过。独立冷启动逐步重放及项目 E3 认证未运行。 |
| 单线程转移微基准 | Gate C，50,000 次 Unpack＋PlayCard＋Pack＋Hash，602.03 ms，**83,053 trans/s、0.0 B/step**（报告精度）。低于上游 100,000 trans/s 门槛，组合退出 1。共享训练负载和低优先级同时存在，单样本无法归因。未做空闲重测或旧版 A/B。 |

首次 Gate A 从 DLL 位置固定上溯六层，错误解析到源码父目录。保留首次失败日志，将相同构建产物放到隔离构建目录多一层的 `net9.0` 后成功执行原生根检查。Godot SDK 与 `tools/Directory.Build.props` 各自指定构建输出。发行 ZIP 首次证书链失败，其后一次下载超时，最终完整下载并以发布页摘要核验后检查内容。

### 复现入口

仓库同级 `hk0-isolated-131d10a/` 保留源码与发行 ZIP、独立构建以及 `output/`。以解包根为工作目录，指定 Steam 安装根 `$steam`、独立输出 `$out` 及现有 .NET 9 宿主 `$dotnet9`。本次只读引用项目既有 NuGet 缓存与安装的游戏、RitsuLib，`DOTNET_CLI_HOME` 使用独立目录。

~~~
$isolated = (Get-Item ../..).FullName
dotnet build CombatSolver.csproj -c Release --artifacts-path "$isolated/build/solver" -m:1 -p:UseSharedCompilation=false -p:CopyModOnBuild=false -p:NuGetAudit=false "-p:SteamRoot=$steam"
$solver = (Resolve-Path .godot/mono/temp/bin/Release/CombatSolver.dll).Path
dotnet build tools/search/OfflineSearchHarness/OfflineSearchHarness.csproj -c Release --artifacts-path "$isolated/build/harness" -m:1 -p:UseSharedCompilation=false -p:NuGetAudit=false "-p:SteamRoot=$steam" "-p:CombatSolverDll=$solver"

# AppContext.BaseDirectory 需距解包根六层
$bin = '.local/tool-build/OfflineSearchHarness/bin/release'
$run = Join-Path $bin net9.0
New-Item -ItemType Directory $run -Force | Out-Null
Get-ChildItem -LiteralPath $bin -File | Copy-Item -Destination $run
$harness = (Resolve-Path (Join-Path $run OfflineSearchHarness.dll)).Path
$env:DOTNET_PROCESSOR_COUNT = '1'
& $dotnet9 $harness --check-hot-layout
& $dotnet9 $harness --verify-hot-parity --gate ab1c
& $dotnet9 $harness --soak-deploy --fights 1 --only-fight 0 --seed 7777 --pool all --profile Low --dop 1 --budget-ms 500 --out "$out/soak-1.json" --dump-outcomes "$out/soak-outcomes.json"
~~~

HP 请求 JSON 含 `characterId=IRONCLAD`、`encounterId=FUZZY_WURM_CRAWLER_WEAK`、`seed=HK0HP20261125`、`initialPlayerMaxHp=HP`、`initialPlayerHp=HP`、`enemyCurrentHp=15`、`clearPlayerHand=true` 和 `cards=[{"cardId":"STRIKE_IRONCLAD","pile":"Hand","count":3}]`。执行 `--request "$out/root-HP.json" --out "$out/hp-HP" --workspace "$out" --profile Custom --beam 24 --nodes 512 --budget-ms 500 --dop 1 --potion-policy Disabled --search-mode Evaluate`。结果见 `quality.json`、`harness-result.json` 及 `route.json`。独立日志包含 `build-solver.log`、`build-harness.log`、`layout.log`、`parity-ab1c.log`（首次失败）、`parity-corrected.log`、`hp-{80,160,999}/` 和 `soak-outcomes.json`。

## 三条独立接入路线

| 路线 | 改动与成本 | 预期收益 | 语义、信息边界与验收 |
| --- | --- | --- | --- |
| **A · 仅用于 DC3A Oracle** | 低到中。复制冻结 Harness，适配根配方并复用 Coordinator、RealCombatDriver，给 `reference.py` 新增独立版本入口及账本。 | 较小迁移面取得复杂战斗的新版参考，首胜后有机会继续压低净损。 | 全信息仅进入 Reference worker 和私有账本。先用公开开发根验证 80/160/999、选择、长战、预算和取消。新旧建根对账，冷启动验证每条候选的公开帧和原生终局，再定配对预实验预算。 |
| **B · 热核模拟，保留模型和公平搜索** | 中到高。先接单 lane Step、公开观测、动作索引和选择续体，再接 SV1、条件世界和反事实分支，沿用原生认证和 Python 模型。 | 减少复制及转移成本，可扩大同预算下的搜索或经验量。实际收益取决于投影、RPC、推断和认证占比。 | 先限定通过定向验证的单人原版内容。验收单步原生差分、II-J/II-K、公开历史不变性、80–999 HP 长战及原模型输入等价，分段量纯核／RPC／搜索推断／经验入库。 |
| **C · 全面迁移战斗架构** | 高。替换旧宿主、预测执行、公开编码桥、状态图、原生审计以及 INF1 身份和恢复。保留能按原版本重放的历史产物。 | 统一使用新内核及搜索，减少长期维护旧栈的成本。 | 同时改变语义与搜索。需先通过 A 和 B，再验收原生胜败、局外资源、Godot ABI、账本恢复与完整回归。NOSL 公共入口与 Oracle 私有入口独立。 |

HK0 的证据足以支持 A 的离线适配和少量同根验证。B 先用带未知抽牌和交互选择的单步见证检验边界，C 等待两条较窄路线的结果。
