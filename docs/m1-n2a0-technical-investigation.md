# M1-N2A.0 · 理想牌序、随机事件分支与循环结构技术调查

2026-11-25。项目 `matrix773768/sts2-cli` 的 `port/v0.113.1`。调查基线 `e00c6ca89b616ef255d6f7ee50e20784d51a3ad7`。Git fetch 在默认沙箱遇到 DNS 限制，允许联网后分别用 Windows 与 OpenSSL 信任库尝试，均遇到证书链错误。通过 GitHub 连接器读取远端分支提交，确认远端、本地跟踪引用和本地 HEAD 三者同 SHA，调查时没有需要合入的提交。

代码证据来自 HK1A 冻结的 CombatSolver 1.0.2 `131d10ae4499b56332787af61fe4a9306e65860f`，游戏为 STS2 v0.113.1 Build 26660232。只读核对 `upstream.zip` 的 SHA-256 与 `experiments/hk1a/hk1a_build.py` 一致，解包树中 HotKernel、HotSearch、循环调查和搜索夹具共 152 项与 ZIP 对应条目逐字节一致。本文的「已确认」指源码、夹具契约或既有报告中的证据。此轮未启动游戏、构建、行为实验或训练，未运行 DC3A 30 秒扩展或 192 根评测。上游源码路径及行号均指该冻结版，旧版路径另行注明。[冻结源码](https://github.com/Torch1230/CombatSolver/tree/131d10ae4499b56332787af61fe4a9306e65860f) · [HK0](hk0-hotkernel-investigation.md) · [HK1A](hk1a-dc3a-integration.md) · [HK1A-Perf](hk1a-perf.md)

## 决策摘要

- **N2A.1 与 SV2A 可以共建随机边界。** 冻结热核可复用牌区、规则执行、合法动作、值复制和从稳定快照回放。需要新增普通抽牌结果注入、公开信念维护和按事件恢复。两种公开研究模式共用相同支持集，NOSL 按条件概率聚合，Ideal 只在指定抽牌事件取 max，Oracle 使用原固定世界执行。
- **先用独立、单线程、有界的小搜索器。** HotSearch 可作为固定世界路线来源。它保留候选父链和路线物化，生产 Beam 的剪枝、分支限额、滚动估值和转置语义需要专门审查后才能用于公开随机搜索。
- **可先提取既有路线中已走过的循环候选。** HotPlanMaterializer 已从热根逐步执行选中路径，适合在研究构建中采集每步状态。冻结版热搜的通用去重、停滞限制及成长保留只覆盖部分需求。旧版周期识别、循环保留与重复回放没有移植到该搜索路径。
- **HK1B0 与 N1A 可并行。** 小夹具单进程使用同一热根复制即可验证协议。敌方机制导出可独立进行。涉及跨回合敌方行为的研究根需先确认该遭遇的执行与公开性，其余可从回合内夹具启动。

研究输出沿用 M1-N 的联合可达性、启动成本和运转收益区分。记录可同时兑现的资源/收益与见证，并在指定视界和生存条件下估计实际启动机会。固定世界最优路线、理想潜力和真实公开策略价值分别有各自定义。项目历史也用了 N2A.1/N2A.2 编号。仓库现有同名报告与目录属于旧 NOSL 交互/训练队列，使用 E3F 0.51.5，不能据编号视为这次的 HotKernel 随机接口已完成。[M1-N §13–27](m1-n-research-design.md) · [M1-SV §6–11、§22–24](m1-sv-research-design.md) · [旧交互资格](m1-n2a1-nosl-interaction-and-feedback.md) · [旧队列资格](m1-n2a2-training-cohort-and-feedback.md)

## A · 普通抽牌与公开条件分布

### 实际执行与可复用接口

| 路径 | 冻结版调用链与关键边界 |
| --- | --- |
| 玩家出牌、用药及效果抽牌 | `HotCombatEngine.Step`（`Sim/HotCombatEngine.cs:287`）调用 `ExecutePlayCard` 或 `HotPotions.UsePotion`。出牌进入 `ResolveMovedCardInPlay` 的卡牌效果，编译效果的 Draw 指令、手写卡牌和 Hook 都可到 `DrawCards`。例如 `HotCombatEngine.Bytecode.cs:187`、`Cards.Core.cs` 的 Impatience、`Powers.cs` 的 Dark Embrace 耗尽触发。丢牌再抽也由 `CardPlay.cs:1111` 进入。牌在 Play 区的结算时序必须保留，正在打出的牌不会因预先纳入弃牌堆而被自己抽回。 |
| 回合开始 | `ExecuteTurnSetup` 或 `ExecuteEndTurn → RunEndTurnBeforePlayerStart → RunNextPlayerTurnStart`，汇入 `RunPlayerTurnSetupBody`（`Turn.cs:809`）。重置资源并结算对应触发，计算 `ModifyHandDraw` 等数量修正，清除已消费的 DrawCardsNextTurnPower。第一回合在抽取前过 Imbued 置底和 Innate 置顶逻辑，再 `DrawCards(..., fromHandDraw: true)`（972），之后还有回合开始 Hook、球与 AutoPrePlay。分段入口 `StepEndTurnBeforePlayerStart`／`StepStartPlayerTurn` 也用于回合开头选择恢复。 |
| 连抽及嵌套 | `CardPlay.cs:879–1010` 的 `DrawCards` 在每次调用检查终局、数量和待选。非开手抽牌先过 `ShouldDraw`，再逐张检查手牌上限、终局及待选。每张经 `HotPiles.DrawTopToHand`（`HotPiles.cs:102`）移动后更新历史抽数、非开手抽数和 Status 计数，触发 `AfterCardDrawn`，再按 UID 重找实例处理 Void、Kingly Kick／Punch、Slither 等内在效果。Relic／Power 可先移动牌、触发其他动作或递归抽牌。Scratch 用 `ActiveDrawDepth` 及 finally 约束递归。每次应以当前状态重新求剩余支持集，批量预抽会改变结算。 |
| 耗尽牌堆 | 单张抽之前若 Draw 空且 Discard 非空，调用 `HotPiles.ShuffleDiscardIntoDraw`（202），然后分派 `AfterShuffle`，再检查牌堆及手牌上限。洗牌收集 Discard 后接 Draw，按原版卡牌比较器排序，执行 `HotRng.UnstableShuffle`，应用 PerfectFit 的原堆监听次序修正，写入 Draw、清空 Discard、更新洗牌事件计数，并包含 Fool 的 Shoot／箭状态处理。具体触发在调用者侧，修改洗牌器仍需检查所有调用者。 |

这一路径的首个普通未知节点可设在单张移动前，晚于适用的阻止抽牌、容量检查及洗牌触发。在当前源码中该处直接读取有序牌顶，没有协程、随机事件请求、注入参数或可序列化栈帧。把整个相关动作包成「抽一张」会错过洗牌 Hook、后续抽牌、真正的选牌及同时发生的资源结算。[抽牌生命周期](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/src/HotKernel/Sim/HotCombatEngine.CardPlay.cs#L866) · [回合结算](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/src/HotKernel/Sim/HotCombatEngine.Turn.cs#L733) · [牌区操作](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/src/HotKernel/Sim/HotPiles.cs#L198)

### 绕过 DrawCards 的取牌及支持边界

| 机制 | 调用证据与首期处理 |
| --- | --- |
| 牌顶自动打出 | `CardPlay.cs:371 AutoPlayFromDrawPile` 会在必要时洗牌，直接从 Draw 逐张移至 Play 预置整个批次，再按 UID 自动打出。调用者包括 Cascade、Havoc（`Cards.Core.cs:601,726`）及 Distilled Chaos（`HotPotions.cs:362`）。未知牌顶和自动目标各有独立语义，首期遇到即停。 |
| 选取／搜索／揭示抽牌堆 | Secret Technique、Secret Weapon、Wish（`Cards.Core.cs:2868`）从 Draw 选出实例后 `MoveCardToHandOrDiscard`。Seeker Strike（2879）先随机取子集，再产生选牌或自动移动。Foregone Conclusion（`Powers.cs:3375`）可先洗牌，再按 Draw 顺序全取或提示选择。Ki Chant（`HotFoolTarot.cs:734`）可先洗牌并恢复原有牌顶，再观察或选择。须区分揭示/随机候选和已公开后的玩家选择，首期限定为 unsupported。 |
| 回收和重排 | Hologram、One for All 等从其他牌区直接取牌，Headbutt 等把已知实例放在 Draw 顶。它们使用移动或选择接口并具有各自满手行为。明确支持的公开移动可更新信念及实例映射。只登记正例，再按调用链扩大范围。重排、置底、从未知中移除或隐蔽观察等路径在缺少对应更新时停在事件前。 |
| 显式洗牌与插入 | Reboot（`Cards.Core.cs:1953`）及 Bottled Potential（`HotPotions.cs:251`）直接洗牌后再普通抽牌。The Abacus、Whittling Knife 和 Biiig Hug 的洗牌 Hook 分别加格挡、施加 Aim、将 Soot 随机插入 Draw（`HotRelics.cs:1659`）。`CardPlay.cs:1514` 对 `dstOffset == -2` 用 Shuffle 流在 `0..zoneCount` 插入。敌人效果写入弃牌可作公开确定性事件，插入 Draw 的位置和限制按实际规则登记。 |

表格覆盖已读到的旁路。新增实验按机制白名单和事件守卫决定覆盖，尤其要审查暗中读取的位置、候选顺序、相等牌代表选择及增长的事件日志。已知顶/底的普通单抽、没有位置相关观察的均匀未知区间、经验证的顺序连抽，以及无顺序修正的普通耗尽再洗牌可分步接入。单张回收洗牌的顺序确定，可优先接入以支持双卡夹具。公开确定性的 AfterShuffle／AfterCardDrawn 可在专项对账通过后保留。PerfectFit、多张 Innate 或 Imbued 的相对顺序、Ki Chant、未知位置塞牌、随机生成/目标/费用（包括 Confused 和 Slither）及顺序敏感的非普通取牌，首期需要显式边界。首期以开手已公开的根规避初始分配问题。若以后研究理想开手，需独立定义更早的根和相应条件律。

### 暂停、分支与恢复

**已确认的可复用模式。** `HotExecScratch.BeginAction` 清并加载玩家选择前缀，`RequestChoice` 和过滤变体消耗前缀，或记录 `NeedsChoice` 与待选组。`HotParallelExpander` 将工作状态和 Cold 重置到 `replayBaseState/replayBaseCold`，执行同一动作和更长前缀（2056–2085）。结算到待选时再用部分状态枚举菜单。结束回合已有回合开始前稳定快照优化（1718–1773）。`Step` 的返回状态包含 `Executed/NeedsChoice/Outcome`，可能已经修改了一部分工作状态。Choices 的生成候选和 UID 过滤器有线程局部缓冲（`Choices.cs:9–24`），需要在当前试次取出稳定副本。`EnumerateChoiceOptionsWithClasses` 读取具体牌区和顺序并做等价类处理，不应借它枚举随机结果。[重放实现](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/src/HotSearch/HotParallelExpander.cs#L2056) · [选择协议](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/src/HotKernel/Sim/HotCombatEngine.Choices.cs#L105)

**推荐的研究入口。** 保留原 Oracle 路径。用窄适配层从动作前（或已验证的回合阶段）完整状态开始，局部使用独立的事件解析器。先实现普通单抽和必要的简单洗牌，按原语义复用移动、触发、合法动作及收尾。输出边界至少区分 `Completed`、玩家 `NeedsChoice`、`NeedsChance`、`Unsupported` 和错误，终局另有明确类型。事件描述包含动作内发生序号、来源/结算阶段、类型、条件支持、可观察时点及已使用前缀。玩家选择记录和随机结果记录分别校验，并记录交错顺序。多次触发同一代码位置时靠动作内序号及来源绑定，验证类型、选项及游标耗尽。随机事件的内部结果永远不编码为 `HotAction`、玩家待选项或可部署动作。

每次试探使用动作前副本、独立 Scratch、独立公开信念及事件前缀。从同一快照恢复 hot、Cold、RNG 和信念，重复执行已记录前缀，仅提交该分支完成的状态及真实事件。暂停必须不再执行后续效果。仅给 DrawCards 加 early-return 不足以保证调用者停止，现有代码多只检查 `NeedsChoice` 或完全不检查返回数量。后续可审计并贯通独立暂停状态，或者在研究构建用专用控制信号在 `Step` 外统一捕获并核查 finally、线程缓冲和嵌套清理。异常开销、逐调用恢复及分叉成本待小样本测量。任一路径都要保证费用、Power、历史及洗牌事件只在提交的轨迹中各发生应有次数。

| 模式 | 共用结算上的区别 |
| --- | --- |
| 固定世界 Oracle | RootState 的真实顺序和原始 RNG 推进保持原执行。可以记录或回放结果以对账，策略允许私有世界内搜索。 |
| NOSL | 以公开历史重建条件分布。事件取条件期望，玩家只在真正公开的观察处决策。同公开历史的隐藏子分支共享决策。隐蔽结果只更新信念，直到可观测时才产生供策略区分的边。 |
| Ideal | 仅对列名后的普通抽牌事件，在同一条件支持集内取 max。已知牌与有且仅有一个结果的节点照常结算。其余已建模随机事件维持概率聚合，缺少模型的节点停止并保留原因。一条含有非理想化随机结果的成功轨迹只提供存在见证。 |

SV1 在旧 II-K.3B 的 `experiments/m1-sv1/build.py` 向旧模拟器注入 `SearchProbe.BeforeDraw/Stop`，在读取牌顶、使用敏感 RNG、牌顶自动出牌或揭示之前停止。它以原动作前状态与触发描述为凭据，恢复已有玩家选择，但没有随机结果注入和已知顶追踪。SV1 的同公开双世界夹具及 A（提交结束回合）和 B（下一公开决策）的边界定义可复用。当前树中未找到已交付的 SV2A/SV2B 热核实现，现有设计规定了公开信念、普通抽牌概率和截断处理。SV4A 等固定世界搜索在随机边界回退到触发前估值，也不能作为条件分支后端。[SV1 报告](m1-sv1-turn-state-graph.md) · [SV1 插桩](../experiments/m1-sv1/build.py) · [SV2 路线及 SV4A](m1-sv-research-design.md)

### 公开信念、实例与 RNG

- `HotRootBuilder.BuildFromLive`（153）产生 `HotRootBundle(Rules, RootState, RootCold)`，按实际顺序导入 Hand、Draw、Discard、Exhaust、Play 并分配 UID（292–299），保存实例修饰与附属数据，捕获 Shuffle、CombatCardSelection、CombatEnergyCosts、MonsterAi 等流（474–483）。`HotContinuationStamp.CaptureFromHot` 包含有序 Draw（125）与 RNG（293–296），只能作私有连续性审计。HK1A 的 Oracle 导出原生续用戳和回放日志。已读的公开观察来自旧 NOSL 宿主，例如 `experiments/m1-nosl3c-iia/PublicEpisode.cs` 的抽牌数、公开牌区及当前敌意图。它们可作公开字段边界的起点。冻结热核未查到可直接输出条件信念的接口，需新建投影和合法历史输入。抽牌张数与初始牌组无法补回所有战斗加入牌或已积累的顺序约束。
- 建议首期用有序已知顶前缀、有序已知底后缀及其间可交换的未知实例多重集，记录洗牌代次、每个约束的公开来源及观察时点。公开置顶／底保持相应顺序，公开移出扣除该实例，洗牌按实际合并和修正规则重建约束。存在内部固定槽、筛选信息、部分揭示、受限塞牌位置或多段相依约束时，要求更丰富后验或明确退出。给定均匀且可交换的未知区段，逐实例概率为 `1/N`，已证明可交换的同类权重为 `n_i/N`，抽后移除并更新后验。连抽按有序条件概率乘积结算，每次触发之后再求下一张。仅当顺序、互动、观察及后继完全等价时才能按多元超几何压缩。实际采样须从公开后验出发并保持已承诺事件。如存在共享流相关性或历史条件改变先验，需要验证后验假设。
- 实例用稳定的研究身份及显式映射，保存升级、动态变量、附魔／Affliction、临时和持久费用、旗标、牌区、引用及生命周期。原版物化按当步卡牌状态键及出现序数对齐。`HotStatePacker.CanonicalizeForPack` 清除无引用 UID，并按碰到顺序重映射必要 UID 及 Cold；`AssignDeterministicCardUids` 为扩展再赋值。二者都不能直接提供跨动作或跨私有世界的公开实例身份。应在移动、生成、复制、升级、污染及移除时同步绑定，按合法观察暴露信息。若仅有卡牌 ID 相同、修饰或引用不同，不合并。若副本确实等价，按实例数合计概率并记录代表映射。
- 执行器可以用由公开约束构造的研究牌堆实现分支。重排时只能改尚未承诺的未知槽，并在真实 `MoveCard` 前注入已选实例，保留其他牌区和后续语义。研究牌堆的占位顺序不可进入策略、评分、候选顺序/并列排序、状态键输出或触发读取。未知区如果被非普通抽牌扫描或依赖其顺序，在读前返回明确边界。严禁换 seed 后保留真实未知牌序，或用真实隐藏顺序/真实 RNG 决定分支值、合法菜单和诊断公开字段。
- `HotRng.UnstableShuffle`（`Sim/HotRng.cs:136`）即使 0 或 1 张也从外层流消费一次 `NextULong`，派生临时 Fisher–Yates 流。`DrawTopToHand` 本身不消费 RNG。Oracle 及指定 Oracle 结果的对账保存每流精确消耗。公开研究分支由公开模型生成结果及显式逻辑事件消耗，不能回退到根私有流；研究随机源另有可复现身份。针对替换/旁路的洗牌，在确定性对照记录是否消费、在哪个阶段消费及 Hook 顺序。所有随机调用和依赖隐藏顺序的操作必须经守卫，否则该环境不进入公平模式。普通洗牌的均匀排列是条件模型，尚未完成所有洗牌先验、原生 PRNG 条件相关性及修改顺序机制的对照。

## B · 循环识别、保留与见证

### 迁移盘点

| 功能 | 旧版证据 | 冻结版状态 |
| --- | --- | --- |
| 路线及父链 | 旧 `SearchNode.Parent`、单步动作、快照和循环证据 | `HotNodeArena.cs:31–82,213–245` 的 `HotSearchNode` 有 `ParentId`、动作/选择、StateHandle/Cold、哈希、动作计数及资源摘要，`ExtractActionNodePath` 可追选中路径。Coordinator 回合间压缩状态 arena（1985–1993、2561），历史节点的句柄不适合直接用来导出完整帧。 |
| 周期识别 | 归档 2026-09-21 的 `CombatBeamSolver.CyclePlanning` 回看至多 32 个动作，先比较 `CycleShapeKey`，再比较动作键、相邻两窗的状态增量，或耐久进展及逐动作伤害相位。形状刻意省略部分动态量。`CycleRegionRetention` 管理区域及替代出口。 | 全查 `src/HotSearch` 未找到周期窗口、祖先形状匹配或 `CycleFamily` 账本。冻结版 `CombatPlan.cs:691 BuildCycleActionKey` 仍供 `SolverOverlaySnapshot` 的显示身份使用，存在 `LoopDisplayChecks`。显示折叠可提供动作形状参考。 |
| 转置 | 历史归档记录部分动态计数及累计 HP 口径曾缺出旧指纹。 | `HotStatePacker.Pack/CanonicalizeForPack` 写入规范状态及有序牌区，RNG、计数等仍在内部状态。`HotHash.ComputeHash` 混入 Cold。`HotTranspositionTable.CheckDominance` 哈希命中校验 packed 字节与 Cold 结构相等，再按战损、动作数、药水/救命资源和分数等标签支配。存在容量门槛和长路线 bypass 设置，部分分支另有本地去重。这是冻结搜索内部转置契约，研究中还须绑定规则、信念、阶段、剩余视界及相关轨迹量。 |
| 无收益循环停止 | `ShouldStopUnproductiveCycle` 等按窗口、耐久/资源进展及族预算停；旧文档指出格挡增益启发式有偏差。 | 仅见相同状态支配、通用 Beam/预算，`MaxActionsPerTurn = 64`（`HotBeamRetention.cs:25`），以及 Coordinator 跨回合进展停滞（1922–1966）。计数或 RNG 改变的空转可避开相同状态剪枝。`RepeatableNoProgressBranchesPruned` 在 `HotPlanMaterializer.cs:474` 固定填 0。少数卡牌自己的内部循环护栏不适用于一般搜索。 |
| 有收益路线与重复试探 | 归档旧版净耐久进展的循环绕过部分停滞预算。归档的逐张重复 P2 当时是建议。本地 II-K.3B 留存源码已存在 `CombatBeamSolver.CycleReplay.cs:11 TryReplayCycle`，例如要求两次周期、耐久下降、HP/能量/星星约束、回放预算，不跳过真正的动作与目标决策。仍逐步执行。 | `HotBeamRetention` 用即时、存活、成长、投资、Rollout 等通用保留维度。`HotParallelExpander` 按实际子状态评分并保留优质线路，能自然走出短生产性循环。未发现旧版周期专用保护、重复试探及其遥测路径。64 动作限制可能截断现有长循环根。 |
| 路线物化与结果 | 历史用平铺 `PlanAction` 部署。II-K.3B `CombatPlan.cs` 有 `CycleShapesDetected`、`CycleReplayAttempts/Actions/Victories` 等聚合指标。 | `HotPlanMaterializer.Materialize`（53）取选中动作父链，从 `RootState/RootCold` 重新规范化和分配 UID，重放 `Step`（148、225）。物化动作、目标、选择、回合续用戳、战损、格挡、剩余能量、药水、洗牌等摘要。没有每个见证的周期、重复次数、完整端点、随机脚本或每轮增量。 |

历史比较以事件语义和实际执行入口为准。冻结树中的归档文档、仍能找到的计划字段和测试夹具属于迁移线索。II-K.3B 证据位于本地 `logs/iik3b-solver/source/src/Search/`，属于项目旧版源码，和归档调查引用的 `3f4002bd` 是两个证据点。[旧循环调查](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/docs/archive/research/loop-quality-performance-display-20260921.md) · [HotSearch 冻结实现](https://github.com/Torch1230/CombatSolver/tree/131d10ae4499b56332787af61fe4a9306e65860f/src/HotSearch)

### 第一版运转结构见证

可先用 HK1A 短路线或两卡正例，从同根回放既有搜索结果。优先在研究构建调用 `HotPlanMaterializer` 的根重放路径并采集稳定动作边界，或者保存动作/选择和根身份供独立运行器重放。仅拿已导出的路线时，按当前实例、目标、选项和回合边界重新绑定。回放要另验 `Executed`、无残留选择、事件前缀完全消耗以及终局；保存每步与路径节点可核对的规范状态摘要。HK1A 已有冷启动原生重放与回合边界/终局对账，现有证据只覆盖部分根，逐动作完整热核/原生帧还需新增专项。用已存在的获胜路径可以分析已经发生的周期；若路线未包含重复、搜索提前截断或没有返回相应路径，需要另搜。理想抽牌脚本可以用研究执行器精确回放，只有给定相容的原生夹具或实际能再现指定结果时，才能另称原生见证。

研究运行器先在轨迹的稳定边界上用粗形状查找候选，如回合及相位、牌区轮廓和可再生资源、活跃敌人集合。可结合动作模板寻找相邻重复窗口，但保留完整实例、目标与选择用于验证。任何形状碰撞均允许进入复核，无权做转置、剪枝、直接乘算资源或提前宣布终局。确认前执行启动前缀，再从完整循环起点分支逐动作重复候选段，重新绑定牌、检查合法性、结算触发，保留真实退出路径，终局中途发生时保留部分周期及具体步号。

| 见证字段 | 内容 |
| --- | --- |
| 身份及协议 | 根/构筑/规则和构建身份，公开历史与约束，Oracle/NOSL/Ideal 及允许取 max 的事件类型，目标、视界、计算预算、来源路线。审计帧私有存放。 |
| 路线 | 启动前缀、候选周期的位置及动作序列、每动作实例/目标和玩家选项、退出或击杀后缀。报告启动动作、回合及资源代价。 |
| 完整状态与差分 | 周期前后完整 hot、Cold、绑定表和规则上下文，公开信念、事件游标及影响合法性的阶段。逐轮记录能量（含入口最低所需及轮内峰值消耗）、星星、HP/格挡、各敌 HP/格挡/存活/相位、有序牌区、费用/附魔、Power、遗物、计数器、药水和 RNG/事件变化。保存导致差分的中间边界。 |
| 随机依赖 | 每次事件的来源、观察时点、可选结果与条件概率或 unsupported、实际解析及需要的指定结果。固定世界的单条成功路径和 NOSL 的启动成功率是独立数据。 |
| 验证结果 | 候选、已验证有限重复、已达当前终局分级。给出完成的重复次数、部分周期、输出与净损。失败明确是动作不可用、资源不足、实例歧义、触发/相位变化、缺随机语义、台账或状态不符、预算/容量截断、胜利或死亡等。 |

空转反例常只改变累计计数，有限重复可因资源下降、增伤相位、手牌饱和、强制结束、敌人阶段或死亡截断而失效。两轮相同差分仅能支持已执行的次数。数学意义的无限需要独立的不变式及每步合法性、条件稳定性、随机依赖和边界证明，本阶段保留有限见证级别。

## C · N1A 敌人机制导出

当前回合执行从 `Turn.cs:489–506` 调用 `HotMonsters.ExecuteMonsterMove`，并在 594 调 `PrepareMoveForNextRound`。实际路径是 `Sim/Content/HotMonsters.cs`，同树里的 `HotCombatEngine.Monsters.cs` 提供类似执行/推进代码，未找到它的该主调用入口。机制抽取必须以现行调用者及内容补偿为准。[敌方回合入口](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/src/HotKernel/Sim/HotCombatEngine.Turn.cs#L489) · [实际怪物执行](https://github.com/Torch1230/CombatSolver/blob/131d10ae4499b56332787af61fe4a9306e65860f/src/HotKernel/Sim/Content/HotMonsters.cs)

- **可直接读取的表示。** `HotRootBuilder.CompileMonsterMachine`（3100）读原版状态机并编译节点。`HotDefinitions.cs:199–249,416–451` 的 `HotMonsterMachine/HotMonsterNode` 有初始节点、MoveId、NextNode、基础攻击数组（基础伤害、段数、标记）、`MoveEffects` 以及分支和一次性字段。`HotRootBuilder` 以 live `NextMove` 绑定 `CurrentMoveNode`（885–891）。`HotMonsterMoveEffect` 提供 op、目标定义、值、flags，可从 `HotCatalog.Monsters.CompileStandardMoveEffects` 抽取受测的格挡、成长／弱化 Power、状态牌等。保留效果发生时点与目标牌区，并区分基础段伤、现时意图和模拟结算值。`HotRules` 的 Cards、Powers、Relics 与 `HotCatalog.*`、卡牌字节码、Power Hook 分发表可提供基础定义、目标、触发类型和字段来源。
- **完整规则须补充语义映射。** 条件节点的 `BranchTargets` 可为空，编译器尝试在导入根求一次 `NextNode` 作为 fallback（3246–3269）。当前运行的 `HotMonsters.ResolveConditionalBranch`（2999）用 real branch rules，例如 Frog Knight 的半血和已充能标志、Test Subject 的 AiRegs 复活阶段、Lagavulin 的 Asleep、盟友数等。伤害和段数可能被 `ResolveAttackRepeats` 等及怪物专用逻辑修正，另外有召唤、复活、行动日志、一次性门控和 Power/Relic 干预。节点表与 HookMask 无法单独给出每种机制的完整条件或效果。N1A 先对短名单导出可校验子图及条件依赖，标记专用处理或未覆盖，执行仍交给冻结热核。短名单可用单段/多段、成长、阶段阈值和塞牌目的区对照约束。
- **公开边界。** 公开规则、当前可见意图、HP 和由公开历史确定的阶段/一次性标记可投影。实际状态机导入还读取根私有字段，运行态有 `AiRegs`、Flags、冷日志及 RNG，不能整体导出给 Actor。内部名称、节点编号、根计算的 fallback 和实例顺序都需要来源审查。项目采用敌人确定或条件确定的前提。冻结执行确有 `PickRandomBranch`（`HotMonsters.cs:2833` 后）使用权重、历史、冷却与 `MonsterAi` 流，Two-Tailed Rat 还有按场面调整权重的逻辑。仅凭实现不能认定已确认原生反例。若某研究根到达尚未确认唯一合法后继的路径，公开模式标为未资格化并停下，同时保留原版点查事项。已确认结果唯一也需保留 Oracle 的 RNG 消耗。确定的敌方动作可包含玩家侧的随机塞牌位置或目标，应按对应事件处理。

## 实施顺序与依赖

| 阶段 | 推荐交付 | 取舍与主要风险 |
| --- | --- | --- |
| N2A.1 / SV2A 共用部分 | 在隔离构建/友元入口确定公开根契约。用固定手牌小根实现稳定快照、事件请求及重放前缀，先接已知顶、普通未知单抽、最多两三张小连抽和单张普通重洗。能同时验证信念、概率、分支、选择及 Oracle 兼容。按需接后续手牌和简单多张洗牌，未完成的部分保留独立边界。 | 先做单线程确定规模穷举。若回放开销经测量占主导，再考虑安全阶段快照或显式 continuation。一次预采整堆可用于对照和固定世界回放，但如果策略提前看见后缀就会产生预知偏差。 |
| N2A.2 | 先从既有路线提取并逐步验证循环，后用相同转移入口建立小研究搜索。先解析玩家决策和指定抽牌，分别运行固定世界、Ideal 和精确小 NOSL 或冻结公开策略。输出启动、有限重复及终局见证，含覆盖、节点、转移、重放开销和原因。 | 备选是扩展 HotSearch，以复用 Beam/并行性能。它的选择分支压缩、资源标签、压缩 arena、启发式和阶段界限会影响完整性与目标覆盖。小搜索器先为这些优化提供可穷举对照，并可保留多条通往同一候选的边。固定路线只覆盖搜索器已经发现的结构。 |
| HK1B0 | 非最小实验的前置。沿用 HK1A 隔离宿主导入和手工小根，每根复用热态值做多次分支。 | 现有冷启动/预热成本影响批量吞吐。较大规模时再做常驻、多根隔离、清理、I/O 与首根/稳态分解计时。不能以 Gate C 的峰值作为随机搜索吞吐。 |
| N1A | 与 N2A 并行。共享版本、规则身份、公开字段及事件契约。第一版循环可限定回合内、已资格化敌人，不依赖 N1A 完成。 | 做跨回合压力、阶段切换和污染时，按遭遇补确定性/公开性资格。先查证会进入的条件路径，无需等待完整机制语言。 |
| SV2 后续 | 小模型校验后，SV2B 扩充普通抽牌概率搜索，SV2C 处理复杂顺序、洗牌及剩余随机机制。N2A.3 再比较厚度、冗余、能量、启动前损失、压力与实际兑现。 | 预算引入概率质量和未解决上下界，不重新归一化丢掉难分支。固定续策的启动分布按该策略解释，不能用逐个私有世界最优后取均值估计 NOSL。 |

建议最小搜索以确定节点数、动作深度、事件深度和重复上限约束。在预算、unsupported 或证据不足时，保留未解决质量和搜索停止点。在启动目标的例子里，已证成功质量为下界，尚未解决的质量加到上界，失败、提前获胜、死亡分别记。固定视界、收益和预算先冻结再比较。理想模式只提供该协议下已发现的潜力和存在见证。

## 夹具与最小验收

| 对照 | 预期检查 |
| --- | --- |
| 既有 `coverage/fixtures/search/two-card-infinite-0170.json` | Ironclad，50 HP Fuzzy Wurm Crawler Weak，0 能量，Flash of Steel 在手、Finesse 在弃。上游原夹具要求至少 19 可执行动作、首回合、预测战损 0、无额外重规划。作为发现回收与逐张重复的正例。所需洗牌含单实例路径。N2A.2 需实际导出周期、验证多次及终局。 |
| 旧循环反例及补例 | `generic-loop-stagnant-block-draw-v0111` 检验空转/格挡饱和。`generic-loop-letter-opener-hidden-phase-v0111` 和 `generic-loop-long-growing-damage-v0111` 检验延迟兑现、每轮不同差分与 64 动作截断。`generic-loop-bloodletting-double-pommel-quality-v0111` 检验有限卖血与替代路线。新增相同形状、下一轮因限次/能量/相位失败的一对，及需特定抽牌的有限循环、难启动和普通构筑。旧断言属于旧搜索口径，冻结版不应默认满足。 |
| 抽牌及 Hook 回归种子 | `card-upgrade-stable-shuffle-0160`、`triggered-shuffle-choice-order-0160`、`joss-paper-shuffle-exact-248`、`dark-embrace-draw-timing`、`turn-start-choice-once-141700-*`、`report-bound-end-draw`。分别用作排序、洗牌/抽牌次序、嵌套、回合开始选择、结算中止的复现材料。原夹具可按受测机制改为最小隔离请求。 `distilled-chaos-nested-choice-405` 是非普通取牌的拒绝正例。 |
| 新概率正反例 | 两未知同类 A 与一张 B 给 `P(A)=2/3`。换成 A 与不同附魔或费用的 A′，需分别绑定；加入已知顶和底，未知步只在中间抽；已知公开置顶/置底、满手、No Draw、空双堆均不得发出多余随机请求。逐步穷举两抽并对手算概率，核对抽牌先后触发；触发中已有选择时需保持边界先后。简单洗牌逐实例对账，Biiig Hug、PerfectFit、Confused/Slither 及不支持的随机搜索候选须出正确原因。 |
| 公开配对 | 制造两根真实未知序和私有 RNG 不同但公开历史相同的根。在同预算、研究采样控制和稳定决策顺序下，公开候选、事件支持及概率、Ideal 输出、NOSL 行动和公共证据一致。Oracle 允许不同。再改真实公开牌顶形成反向对照。加一个「先选动作、后得信息」的手算树，验证不能把逐世界最优平均作为 NOSL，选牌列表也不含随机结果 token。 |
| 回放与隔离 | A/B/A 和反序执行同一父状态的不同结果，核对父状态不变和两次 A 完整相同。同脚本重跑逐步比较热态、Cold、合法菜单、实例/牌区守恒、RNG 流事件次数、触发顺序及终局戳。增加重复事件序号、错误结果、过期选择、漏脚本和预算截断各一例。对精简 Oracle 正例做一次原生同世界对照，再测试已标明不支持情形不会落到真实隐藏结果。 |

本轮仅核对夹具、调用链和已有证据。仍待验证的工程障碍是暂停跨嵌套传播、公开信念在所有支持牌区变动上的同步、真实 RNG 消耗与研究模型的对账、各类选择和指定抽牌混合的逐步重放、终局时点及跨回合敌方条件的资格。冻结版的已有 Hook、快照和路线为这些验证提供入口，下一阶段验收通过前仅使用有界、标明覆盖范围的研究输出。
