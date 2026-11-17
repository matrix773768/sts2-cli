# M1-P0 高速模拟与 CombatSolver 性能调查

调查日期为 2026-11-17。sts2-cli 基线为 `port/v0.113.1` 的 `a708d4d24bcc5b66ea1e6e745b6365974196226f`。CombatSolver 以当日 GitHub main 的 `78e4545e825e58c3d999354b1ffcd54241b1d2cf` 为准。该提交的清单版本为 0.51.5，最低游戏版本 0.113.0，最低 RitsuLib 0.6.11。下文另行标识历史实验版本。[固定源码及清单](https://github.com/Torch1230/CombatSolver/tree/78e4545e825e58c3d999354b1ffcd54241b1d2cf)

**建议 M1-P1 先做原生常驻 worker 的分段计时与重置差分，随后用同样的固定脚本测批量协议。** M1-B2 最大计时段是冷 `load_save`（1.422 秒 P50），其中一次性初始化的份额未知。批量 IPC 单独实施离 100 毫秒仍很远。CombatSolver 提供了可借鉴的战斗快照和预测执行机制，接入优先验证当前战斗的固定脚本及原生差分。

## 1. sts2-cli 的成本

M1-B2 在 Windows、i5-13500H、CoreCLR 9.0.7、游戏 0.113.1 / Steam Build 26660232 上测量。一个 Neow 后地图根，两条 Ironclad A0 脚本，每条 26 步，到首个战斗奖励决策。每个并发档 12 个分支，每分支启动新引擎。36/36 分支与串行参考的逐步决策及地图一致，全部正常退出。分支框架及原生代码从 M1-B2 提交 `4231f82` 到调查基线在这些路径上未变，Benchmark 的策略生成改为引用 `room_policy`。引用的数据来自原脚本。[M1-B2 报告](m1-b2-benchmark.md)

| 并发 4 成本 | P50 / 分支 | 实际路径 |
| --- | ---: | --- |
| 启动及握手 | 141 ms | `SearchEnv.reset` 关闭旧实例，`EngineClient` 建独立 profile、启动 .NET、建立管道和三条读写线程，等待 ready 和版本。 |
| `load_save` | 1,422 ms | `Program` 解包 JSON。首次 `RunSimulator.LoadSave` 执行 Mod/模型库、本地化、SaveManager、Harmony 补丁和模型 ID 初始化，再校验 schema、反序列化 `SerializableRun`、构建 `RunState`、挂载 selector 与事件、Launch/EnterAct、恢复已走坐标和未知节点概率、返回决策。含 IPC、首次路径 JIT 和决策构造。 |
| 26 次动作请求 | 360 ms | Python JSON/命令日志、队列与管道，C# 解包、原生动作执行、等待和观察构造，再序列化及 Python 解码。除以 26 约 13.8 ms/请求，含地图选择、出牌及结束回合，单次状态转移耗时待测。 |
| 逐步 `get_map` | 39 ms | 每个有根的步骤另发一次地图请求。地图遍历、往返和完整决策/地图规范化进入回放记录。 |
| 脚本总计 | 422 ms | 含上述动作和地图，也含轨迹、观察副本及推进循环。 |
| 关闭回收 | 31 ms | graceful quit 清 selector 和 RunManager，父进程等待退出并回收管道线程，超时杀进程。日志和独立目录留作诊断。 |
| 端到端 | 2,047 ms | P95 2,125 ms，批次 1.935 个有效分支/秒。引擎总峰值约 467.9 MiB，单引擎峰值 P50 约 118 MiB。 |

本次只重算已有 `samples.jsonl` 的并发 4 样本（n=12）。`load_save` 范围 1,360–1,485 ms，动作合计 298–421 ms，脚本总计 406–438 ms，指纹 P50 16 ms。恢复核验、恢复地图及轨迹的 P50 落在计时分辨率下，观测最大值分别约 15、16、32 ms。各行中位数不可直接相加。首次 `start_run` 约 2.109 秒，位于正式批次之外。内存是采样工作集，分配量及短时峰值未测。

保存走 `RunManager.ToSave → SaveManager.ToJson → 写文件`，新地图检查点还要核对构建、SHA、观察和地图，并启动独立分支验证；保存开销未进入上述分支计时。Python 的 `SearchPosition` 是地图检查点加动作前缀，恢复中途位置要重新加载并逐步核对回放，并无战斗内存克隆。调度器按分支创建环境，负责截止时间、取消、边界和退出码检查。原生动作还会泵同步上下文，等待执行器或回合稳定（源码有 1/5 ms 轮询，以及特定路径的更长等待）；选牌/奖励可以暂停在活跃续体。战斗观察还生成牌面预览等字段。现有数字无法拆出管道、JSON、观察构造、原生规则和等待各自耗时。

## 2. CombatSolver 当前架构与证据

- **根与动作。** 主线程从游戏 `CombatState` 捕获 `CombatRootSnapshot`。内部 `SimulatedCombatState` 保存战斗规则、战斗参与者、卡牌和效果引用、怪物 AI、历史、遗物等根数据。内部 `CombatPredictionSimulator` 建预测状态、RNG 集、历史和状态库，靠镜像命令/Hook 执行出牌、用药、选牌和回合推进，可在无 Godot 场景树的普通 .NET 进程执行预测。类型及素材仍来自 STS2 程序集，部分根初始化需游戏逻辑。未支持语义可产生风险或明确边界。[根捕获](https://github.com/Torch1230/CombatSolver/blob/78e4545e825e58c3d999354b1ffcd54241b1d2cf/src/Runtime/CombatRootSnapshot.cs) · [预测执行](https://github.com/Torch1230/CombatSolver/tree/78e4545e825e58c3d999354b1ffcd54241b1d2cf/src/Engine/InCombat/Simulation)
- **Fork。** `CombatPredictionSimulator.Fork` 检查可分叉边界，用 `PredictionForkContext` 重映射状态和状态库，分叉 RNG 和历史。集合采用写时复制，例如 `ForkableList/Dictionary/Set`；可变 Power、登记卡牌、部分监听者和引用仍需复制或重映射，首次写入共享容器也要付费。普通 Fork 对某些挂起续体有门禁，选择和跨回合复用另有检查点路径。成本随牌堆、Power、历史及首次写入变化。[Fork 与集合](https://github.com/Torch1230/CombatSolver/tree/78e4545e825e58c3d999354b1ffcd54241b1d2cf/src/Search)
- **搜索。** `CombatBeamSolver` 执行受时间、节点、分支和内存限制的多阶段 Beam Search。一次展开可能进行多次候选回放、选择分支和状态转移，再做终止判定、状态评分与保留。ParallelExpansion 经父对象门闩准备私有 Fork，由 worker 推进，按序提交批次。固定合并顺序减少调度影响，限时或内存截断仍可能改变完成工作量。状态键是双 `ulong` 指纹，战斗状态、续体相关数据及 RNG 等参与等价判断所需的键构造。保留与已展开的转置表以指纹为键，按用药数及战略成本、未来 HP 代价、累计失血、动作数和评分维护非支配标签，常见单标签内联存储。该键用于搜索去重，跨进程差分应另外比较规范化状态。[搜索及转置表](https://github.com/Torch1230/CombatSolver/tree/78e4545e825e58c3d999354b1ffcd54241b1d2cf/src/Search)

**离线入口。** `OfflineSearchHarness` 是 .NET 9 测试 CLI，依赖 `sts2.dll`、`GodotSharp`、Harmony、RitsuLib 和 CombatSolver。它初始化游戏静态状态，使用内存存档层及 Godot 替代路径，创建场景并推进至首个玩家回合，运行 `Evaluate`（单次求解）或 `Coordinator`（生产协调器，可含组合成员）。它支持固定场景夹具，拒绝通用恢复快照等参数。本次未找到公开的外部战斗 DTO → 单步/终态 API。公开的 `PreCombatForecastApi` v6 接收原生跑局/规划快照与遭遇配置，通过隔离 Windows headless 游戏 worker 恢复跑局并搜索，可在清理完成后复用 worker。假设样本入口使用样本 RNG。现有内部 `Replay` 已按顺序执行 `PlanAction` 并处理选择和收尾，可借此做同版本测试包装器，固定策略也可逐次读取合法决策。两者都可绕开候选展开和评分，需要单独定义根输入、动作映射及返回值。固定前缀 Benchmark 调用的是带前缀的 Solve，可做续搜对照，单步计时需单独布置。[离线宿主及固定前缀工具](https://github.com/Torch1230/CombatSolver/tree/78e4545e825e58c3d999354b1ffcd54241b1d2cf/tools/search/OfflineSearchHarness) · [v6 API 源码](https://github.com/Torch1230/CombatSolver/blob/78e4545e825e58c3d999354b1ffcd54241b1d2cf/src/Api/PreCombatForecastApi.cs) · [内部回放](https://github.com/Torch1230/CombatSolver/blob/78e4545e825e58c3d999354b1ffcd54241b1d2cf/src/Search/CombatBeamSolver.Expansion.Replay.cs)

| 性能证据 | 测量结果与适用范围 |
| --- | --- |
| 历史铁甲精英，0.111.0 / Linux / VeryHigh / DOP16 | 完整 Coordinator 请求 39.414→10.578 s，展开 143,651→26,268，转移 834,338→126,358，RSS 高水位 17.486→5.974 GB。由候选数据计算约 2,483 展开/秒、11,945 转移/秒，或每次展开摊销约 403 µs、每次转移摊销约 84 µs。共同分母是完整请求墙钟，包含不同数量的搜索、评估及回收工作和多个 worker，不能分解为单次 Fork/动作耗时。节点额度 500,000、命令时间参数 300,000 ms、实际 profile 600,000 ms、实际请求耗时及工作量是各自独立字段。 |
| 历史储君首领深搜 | 采样分配约 12.72 GB，Fork 栈约 3.94 GB、Snapshot/评估约 1.80 GB。CloneModel、状态及牌堆 Fork、过滤为显著分配来源。CPU 诊断尚有未解析托管栈和 CLR/JIT 成本；线程墙钟含等待，无法给出可移植的 Fork CPU 百分比。转置表、候选/路径存留、GC 和并行积压会影响峰值，分配总量与 RSS 各自计量。 |
| 有效与否定的实验 | 有序监听者参与位图、续体复用和受证明约束的剪枝减少扫描或重复工作，阶段 ABBA 在部分重根有效。上面的铁甲收益来自完整胜利见证交接与单次压缩检查点组合，主要减少搜索次数。11 根/44 次交错中质量字段一致，严格组件资格仅 2/11。仅交接见证的一版在亡灵首领峰值 +38.8% 而撤回；额外压缩版本出现猎手战损退化。储君 Fork 监听缓存候选同工作量约 1.00×，保守峰值比 1.147，未通过。伤害目标过滤只在单根约 3.1%，未纳入该阶段 PR。 |

历史结果来源为 [完整胜利证明实验](https://github.com/Torch1230/CombatSolver/blob/78e4545e825e58c3d999354b1ffcd54241b1d2cf/docs/performance/plan-witness-propagation-20261006.md)、[储君分配与 CPU 诊断](https://github.com/Torch1230/CombatSolver/blob/78e4545e825e58c3d999354b1ffcd54241b1d2cf/docs/performance/regent-search-cost-research-20261005.md) 和 [重战斗阶段 ABBA](https://github.com/Torch1230/CombatSolver/blob/78e4545e825e58c3d999354b1ffcd54241b1d2cf/docs/performance/veryhigh-dop16-20261001.md)。

当前工具包括 `PerformanceBenchmarks` 的固定输入、结果/工作计数比较和运行时采样，OfflineSearchHarness 的初始化阶段计时、内存采样及逐字段对照，以及长期会话的 EventPipe/GC 录制。比较工具区分 transitions、forks 和额外前缀复制。此次沿用已发布实验与原日志，未新跑战斗。当前 0.51.5 + 0.113.1 的单动作、独立 Fork/首次写入、导入导出及跨模拟器一致性没有实测值。现有宿主运行的是搜索且需要同版本运行环境，无法从结果反算这些指标。两边的分支/秒和展开/秒不宜互比。[Benchmark 工具](https://github.com/Torch1230/CombatSolver/tree/78e4545e825e58c3d999354b1ffcd54241b1d2cf/tools/performance/PerformanceBenchmarks)

## 3. 整合边界

路线 A 的最低成本形态是 **native 开房 → 捕获当前战斗 → CombatSolver 预测 → native 合法回放 → native 产出战后状态**。可用于选择或给候选打分。若每个候选仍需 native 回放，完整房间训练吞吐仍受原生执行限制。直接提交预测终态需要双方逐项约定以下数据与语义。

| 边界 | 合同 |
| --- | --- |
| 角色、牌组及卡牌实例 | 记录稳定实例身份、原牌组与战斗副本关系、牌堆次序、升级/附魔/临时费用、生成或变形来源、同 ID 重复牌。动作绑定实例、目标及显式选择，每步按实际合法集合校验。 |
| 玩家、怪物及运行资源 | HP/最大 HP、金币、格挡、能量、Power、召唤物、怪物 AI、药水槽/库存和遗物计数/状态及监听顺序。展示用 `combat_play` JSON 只是观察，不能恢复完整运行状态。 |
| RNG 与 SL | 记录当前战斗相关子流的种子与计数/状态、抽牌和洗牌顺序、随机目标、怪物行动及可能改变的非战斗流。预测限于已合法进入的当前节点；未选地图节点只能用与实际未来随机结果无关的假设样本。局外策略不得通过精确开房预测 API 获取未选节点结果。 |
| 战斗结算与异常 | 差分比较每步牌堆/敌人/续体/RNG 及终态永久变化，包括掉血/回血、Max HP、金币、药水消耗/生成、遗物计数、永久加删改牌、奖励及地图边界。原生执行作为核对基准。未知卡、遗物、事件、Mod Hook 或版本语义以明确的 unsupported 边界终止预测并回原生。 |

路线 B 可从 CombatSolver 借鉴不可变根、分层写时复制及显式续体，逐步构建自己的跨房间核心。它适合批量训练，但需重新维护规则覆盖、版本适配、原生差分及训练样本的分布一致性。路线 C 保持游戏规则由原生执行，优先保住现有确定性与事件覆盖。即使两边均依赖同一版本 STS2，二者的运行时补丁、对象所有权和状态表示仍需验证。

## 4. 最多三项实施优先级

| 顺序 | 方案、改动面及可消除成本 | 风险、最小验证及目标 |
| --- | --- | --- |
| 1 · C | **常驻原生 worker + 有界动作批处理。** 中等难度。先在 `RunSimulator/Program` 拆分冷初始化、schema/解析、构图、Launch/EnterAct、观察、逐动作等待与清理时间。让 `EngineClient/SearchEnv/branch_scheduler` 顺序租用隔离 worker，超时或重置失败丢弃。随后将固定脚本交给原生循环，复用合法动作和决策边界，返回停止索引及必要轨迹。摊薄启动、初始化、关停与 IPC/日志成本。 | 重置须处理 singleton、重复事件订阅、selector/TCS、同步队列、随机流和缓存。最多两夹具，冷进程参照对照同进程 A→B→A 及另一 worker；核对逐步决策、RNG/存档和终态，并验证取消、脚本中途选牌和坏 worker 淘汰。批量实验先保留等价逐步轨迹，再量精简观察的增益。按现有 P50，单删 360 ms 动作请求整段仍约 1.7 s；即使脚本外成本全免，现有脚本本身仍约 422 ms。可改善原生训练样本生成速度，10–100 ms 需同时降低热恢复及原生等待/观察，当前无证据。 |
| 2 · A | **CombatSolver 固定脚本适配与差分。** 中高难度。用同版本独立离线包装器生成当前战斗根，复用内部回放/预测推进；先测导入、Fork、Fork 后首次写、无搜索动作、导出，独立记录搜索展开计数、托管分配和峰值。免去候选里的原生动画/调度、逐步 IPC，以及 Beam 搜索成本。 | 同一小战斗和含洗牌/药水或多选的战斗均做固定脚本逐步差分，特别检查永久状态及跨进程 RNG，并保留 native 回放兜底。优先做接口与覆盖诊断，再按实测决定是否优化 Fork/评估。10–100 ms 的战斗热执行有待验证，完整房间还需要廉价 native 开房和可信结算。可训练战斗价值函数，训练跨房间价值前须解决长期状态与覆盖偏差。 |
| 3 · C→B | **结构化内存快照/恢复，必要时演进独立核心。** 高至极高难度。先在原生稳定边界试验保留已解析、不可变的存档表示，再评估能否减少 RunState/地图重建；若原生对象图复用代价过高，独立核心按需要实现可复制房间状态。涉及快照、运行时生命周期、状态模型与差分工具。 | 只缓存解析结果依然支付 Launch/EnterAct。直接克隆 native 对象图可能遗漏静态引用、订阅、未完成任务或 RNG；内存快照为进程局部，跨进程仍需规范化可移植检查点与差分。先分项计时，再做父/兄弟分叉隔离、两进程重复、下一自然边界检查。独立核心有望支撑高吞吐价值训练；覆盖成本最高。10–100 ms 是目标，精确完整房间尚未证实。 |

M1-P1 的交付应是同一固定脚本下的冷/热分段数据、跨进程重置差分和常驻可行性结论。26 步房间的 100 ms 预算即使完全留给动作也只有约 3.85 ms/步，10 ms 约 0.38 ms/步。完整房间还需要入口恢复、合法决策推进和原生等价的结算。优先去掉已知最大冷成本并测明热下限，才能判断是否需要把更多规则迁入独立高速核心。
