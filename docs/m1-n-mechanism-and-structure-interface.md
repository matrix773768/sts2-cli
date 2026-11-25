# M1-N1A / N2B 公开机制与结构监督接口

本阶段实现了 HotDraw 独立机制导出与证据转换。基线为 N2A.3 `096cd0092982569a651ce633746195733e3d4031`、CombatSolver 1.0.2 `131d10ae4499b56332787af61fe4a9306e65860f`、STS2 v0.113.1 Build 26660232。35 个根用于开发诊断。实现及实验产物位于 `experiments/hotdraw/mechanisms/`，构建通过隔离副本完成。

相关基线：[M1-N 研究设计](m1-n-research-design.md)、[M1-SV 研究设计](m1-sv-research-design.md)、[N2A.0 技术调查](m1-n2a0-technical-investigation.md)、[N2A.1 HotDraw](m1-n2a-hotdraw.md)、[N2A.2 结构发现](m1-n2a-hotdraw-structures.md)、[N2A.3 可达性](m1-n2a-hotdraw-reachability.md)。

## 实际网络输入审查

| 范围 | 当前输入及保留能力 | 当前表达边界 |
| --- | --- | --- |
| 卡牌和牌区 | PRE1 对 deck、hand、discard、exhaust 和当前 candidates 分别编码。实例特征保留升级档、公开费用及其缺失标记、附魔与 affliction 的身份和量、候选选中状态。动作引用可取回当前手牌或选择候选实体。 | 区域读出是带规模归一化的和。区内顺序与区域之间对应实例的历史移动，从全局读出中无法恢复。已知顶底、条件未知多重集及费用修正的来源/过期、完整动态变量未成为显式张量。 |
| 静态卡牌规则 | N2E 提供升级档、资格状态、费用、X 费用及前四个有序效果槽。每槽含操作类别、量、段数、次数与少量目标和修正位。 | 第五个及以后效果只有 overflow 位。完整条件、触发、实例引用及其他 Power 身份未从效果表进入网络。 |
| 玩家和历史 | 有 HP、格挡、能量、星星、手牌及牌堆计数、回合、药水数量、选择上下文和五类常见 Power。24维观察与动作摘要按三个时间尺度更新。 | 具体药水/遗物身份、完整 Power 与计数器、长期动作序列和持续时间没有显式输入。 |
| 敌人 | 敌人张量含 HP、格挡、伤害总量、攻击段数、意图类别和五类 Power。动作可索引选择目标的单敌人向量。 | 每段伤害向量先缩为总量和段数。敌人图、未来行动状态、条件依赖和一次性转换缺席。状态读出将敌人实体合为一个 token。 |
| 全局和行动条件 | 共享编码器将五个区域、玩家、敌群、历史送入两层交互，当前行动结合手牌、候选和敌人引用，以及费用、每段伤害、段数、格挡、抽牌的预览。 | 汇总可能令细粒度关系难以区分。该结论来自张量与聚合代码，尚无策略归因实验。 |

SV3A 共享编码器用 12 维行为策略 embedding 分别条件化 V 与 Q。DC2B 保留该路径，把输出换成死亡类别及 87 个带符号净战损中心。训练各取 V 和行为已选动作 Q 的交叉熵并求均值。潜力、启动、随机条件后的续策、耗尽是否必要，仍须由搜索或统计估计。规则输入提供这些估计所需的条件。

[PRE1 特征](../experiments/m1-pre1/features.py)、[共享编码器](../experiments/m1-pre1/network.py)、[SV3A 模型](../experiments/m1-sv3a/sv_model.py)、[DC2B 价值](../experiments/m1-dc2b/value.py)、[DC2B 训练](../experiments/m1-dc2b/fit.py)。

## N1A 首版公开导出

`ExportMechanisms` 接收已通过 `Session.Open` 的公开快照。夹具按配方绑定实例，按公开条件分区初始化 `DrawBelief`。处理未排序的未知区、已知顶和底时继承原 HotDraw 契约。导出状态来自 `Session.PublicJson`，包括持有实例及区域、升级、当前基础费用、临时费用修正与过期位、装饰信息、变量增量、能量、HP、格挡、相位和当前敌方动作。有效费用由冻结引擎 `GetEffectiveEnergyCost` 计算。费用快照独立标出，X 费用等语义仍需结合卡牌标志和实际合法菜单。

卡牌规则独立保存基础与升级变量、目标、关键词、Hook、特殊处理身份和 `HotRules.GetCardOps` 的有序操作原语。操作参数的整数是冻结解释器的原始操作数。Flash of Steel、Burning Pact、Headbutt、Offering 附带经过执行分支核对的已知操作顺序，分别覆盖伤害与抽牌、选择耗尽与抽牌、弃牌回收到已知顶、扣血与存活后能量和抽牌。其余专用执行留有覆盖标记。Power/遗物保存目录身份、公开堆叠、类型、特殊机制和 Hook 身份。费用原始过期位的 0、2、4、6 分别表示战斗结束、回合结束、打出时、回合结束或打出。

敌方目录用 `HotRules.GetMonsterMachine` 获取，当前行动节点仍由公开状态提供。导出初始节点、动作节点、分段攻击、效果、转换目标、一次性约束、冷却及编译后的条件种类。冻结执行入口为 `HotCombatEngine.Turn.cs` 中的 `HotMonsters.ExecuteMonsterMove` 调用，手写覆盖和条件解析位于 `Sim/Content/HotMonsters.cs`。例如 Fuzzy Wurm Crawler 的第一发 4×1 后接 INHALE，普通同为 4×1 的 ACID_GOOP 后接 FIRST_ACID_GOOP，INHALE 的 7 Strength 可与专用执行分支对账。Test Subject 的复活分支留下两种命名候选及阶段依赖。私有阶段寄存器的值及根导入时碰巧解析的条件后继均不输出。随机边的权重由原版实时回调取得，首版留空。目录捕获攻击值仍需逐敌人验证对动态值的处理。当前图目录资格和公共执行资格分别记录，遇到无法由公开输入确定后继的分支保持未资格化。

当前覆盖集中在稳定研究边界。Power 的内部载荷、遗物进度、公开可重建的长期计数、冷侧引用、全卡池的生成链、完整专用怪物动作与跨回合公开事件资格仍缺。未来扩展应沿公开动作历史逐机制重建计数，保留来源与生命周期。导入成功只能说明提取了目录和公开状态。

[机制导出代码](../experiments/hotdraw/mechanisms/MechanismHarness.cs)、[原公开快照](../experiments/hotdraw/Session.cs)。

## N2B 数据合同

统一查询为 `query(h, g, T, protocol)`。离线输入的 `h` 来自机制导出。目标 `g` 由请求的结构族和卡牌模板角色、身份、升级、目标槽位构成。未来部署需从公开规则目录、公共候选生成器或显式请求取得同形目标。每个公开输入保持 actor 可取得的字段，搜索返回的终局、后验轨迹、实际成功标识及精确参考状态另存于原始标签。视界区分启动行动、战斗行动和随机事件。Startup 优化入口，Fight 与 Switch 优化胜利，Switch 使用候选周期引导动作排序，IdealStartup 在放宽抽牌节点的条件下优化入口。数据头的 `boundObjectives` 标记各臂概率界所对应的目标。

| 证据 | 数据位置及读法 |
| --- | --- |
| 构筑、根及目标 | `labels.variant/rootKey/target` 保存冻结配方变体、公开根摘要及精确入口对照。原始版本与摘要沿来源哈希索引。 |
| 理想见证 | `discovery` 含见证、启动、周期、验证轮次、预算和停止状态。`structureEvidence` 保存 13 个 N2A.2 完整结果，可按 `structureSource` 查原始结构。 |
| 启动与兑现 | `outcomes` 原样保留目标相关 `Lower/Upper`、入口权重、入口时的动作/回合与 HP、能量、格挡、耗尽差分。实际入口续策界及审计轨迹保留于 `Continuations/Entries`。 |
| 策略联合结果 | `Joint` 保留各具体策略中入口与战斗结局的联合概率、带符号净战损及所记录的资源。直接胜利、经入口胜利、经入口后遵循周期动作的胜利均有独立字段。该周期动作指示沿用 N2A.3 的定义。 |
| 固定脚本与自适应 | `scriptComparison` 保留专门的 conditioned 脚本、实际自适应及 Ideal 对照。`lapAudit` 保留逐步重复证据及停止。 |
| 缺失和边界 | 未发现与发现预算、`SearchStops`、`EntryUnresolved`、`Unresolved`、`Unfinished` 均保留。没有已认定目标的根仍可有直接胜利。 |

下界与联合直方图对应实际合法策略，最优上界可能属于其他策略。入口条件续策的兑现值只能沿同一入口分布加权。Ideal 的取 max 证据单独使用。有限轮次、固定视界与预算截断均由原语义解释。已报告的持久资源限于证据中实际保存的项目，跨战斗遗物与成长经济需单独采集。加载器使用 `inputs` 构建 actor 张量。原始结构证据和标签中可能存在私有回放审计字段，应只由监督构建与审计管线读取。

[证据转换](../experiments/hotdraw/mechanisms/dataset.py)、[诊断入口](../experiments/hotdraw/mechanisms/check_interface.py)。

## 公平与诊断

- 35 个夹具均通过公开导出配对，其中 7 个有至少两张可反转的未知牌。每个夹具替换所有 HotKernel 私有 RNG 流并重新公开导入，比较完整导出序列化结果。数据集逐根对账 N2A.3 已存公开状态，并验证 140 个协议臂的概率界及联合质量。
- 牌组位置三组对照使用相同静态卡牌多重集，将 Defend 置于手牌、未知抽牌或弃牌。费用和触发分析使用 `energy0/energy6` 与 `no_draw` 的公开差异。原 N2A.2 的 Letter Opener 测试提供三技能触发的原生对账；首版只输出遗物 Hook 身份，未提供可用于任意当前相位的模三进度。
- `core50` 启动和胜利均为 1。`core80` 同样达到已确认入口，但该案在 24 行动战斗视界内无胜利。`ordinary_direct` 由 Fight 直接获胜且未启动；`quick_kill` 经过合格入口，Fight 可直接出其斩杀牌且周期动作质量为零。
- `startup_unknown` 启动概率为 1，归档含 12 个到达入口，代表性入口消耗 6 HP、增加 2 能量。将初始 HP 配对为 6 和 7 后，启动概率分别为 0 和 1。当前队列未找到理想入口成功但公平入口上界严格低于 1 的配对。
- `conditioned` 在专项 16 行动对照中，为 1/128 固定脚本、1/64 自适应、1 Ideal。整场 24 行动的 29/1024 战斗值属于另一个协议。相同理想胜利质量 1 下，`discard_redundant_finesse` 的公平战斗质量为 23/256，两案兑现差异保留在标签。
- `energy_limited` 与 `energy6` 实际完成 4 与 6 轮后耗能停止。`energy6_hp45` 于完成四轮后在下一段达到胜利。
- 耗尽必要性保留未解决。N2A.1 的 Burning Pact 回归确认实际耗尽一张并触发 Dark Embrace，N2A.3 的同手牌 blocker + Burning Pact 根却在行动零已通过周期入口验证。该夹具的对照会混入抽牌效果和阻塞位置。可继续寻找在入口视界内仅改变合法移除机会的同位置对照，并保留对照臂的最优上界。
- 敌方的同攻击、不同后继与成长对照直接读取真实目录。另从 Test Subject、Lagavulin Matriarch、Slumbering Beetle 遭遇读取五个敌种，涵盖多段伤害、负面效果、复活和睡眠条件。目录对账示例包括 Lagavulin 的 DISEMBOWEL 9×2 和 SLASH 19×1。额外合成检查验证 12×1 与 6×2、回合结束与战斗结束费用修正会在查询输入中保留可辨差异。合成对照用于格式验收，真实等总伤攻击配对、完整持续与爆发压力、修正到期逐步执行仍需另行资格化。

## 实测成本、回归与复现

隔离构建中，公开状态、卡牌、Power/遗物及敌图合并导出每根预热一次后测 25 次，根内均值的队列中位数 0.355 ms，最大 0.641 ms。原生宿主初始化和根导入的冷启动中位数 3.45 s。Python 读取、对账、监督构造耗时 63 ms，序列化与 gzip 131 ms，输出 195,636 字节。测量覆盖夹具导出和证据搬运，应另行测量在线跨回合提取与批量搜索。

N2A.1 通过 15 个原夹具，含耗尽、重洗、顶底、费用与双私有根。N2A.2 通过 13 个原夹具，含长循环、原生 Letter Opener、有限能量、随机不匹配和 unsupported。构建经过相同游戏、上游归档和运行时哈希核验。初次探测 Lagavulin 的遭遇名猜测失败，按冻结夹具更正为 `LAGAVULIN_MATRIARCH_BOSS`。Beetle 为三敌遭遇，移除单敌 HP 注入后探测成功。

```powershell
$p = "experiments/hotdraw/mechanisms"
python "$p/build_mechanisms.py" logs/n1a-build --archive ../hk0-isolated-131d10a/upstream.zip --steam "$env:USERPROFILE/Desktop/STEAM"
python "$p/run_mechanisms.py" logs/n1a-build/build.json logs/n1a-run
python "$p/check_interface.py" logs/n1a-run/exports.json.gz logs/n1a-run/dataset.json.gz logs/n1a-run/diagnostics.json
python experiments/hotdraw/check.py logs/n1a-build/build.json logs/n1a-regression1
python experiments/hotdraw/structures/run.py logs/n1a-build/build.json logs/n1a-regression2
```

[公开导出产物](../experiments/hotdraw/mechanisms/exports.json.gz)、[监督数据](../experiments/hotdraw/mechanisms/dataset.json.gz)、[机器可读诊断](../experiments/hotdraw/mechanisms/diagnostics.json)。

## 后续目标条件评价和消融

离线先对固定、可公开取得的候选目标生成区间监督。部署可以缓存机制目录和目标模板，单次价值调用成本低，代价是离线必须覆盖足够多不同目标与入口。候选目标仍需和运行时选择规则匹配，训练需包括实际候选生成器提出但低价值或尚未解决的目标。搜索内按需生成目标可利用当前公开历史，应记录搜索使用的实际预算、何时查询价值及短程撤回，测量重规划和重复提取开销。模型预测排序可用于挑选下一批求解对象，概率证明依旧来自有界搜索。

建议在相同训练样本、墙钟/节点搜索预算和多随机种子下做五组对照。先比较原 DC2B 输入与同架构扩展机制输入，再比较仅用人工派生特征的 MLP 与保留实体映射/规则边的关系编码器。对同一编码器比较通用价值单任务、通用价值加结构辅助监督、额外提供目标实体的联合任务。机制消融逐组移除敌方图、分段、公开牌序、费用持续期、Hook 与历史。目标消融控制训练步数和候选产生路径，分别报告直接收益和启动的分布。主要指标用原协议的战斗胜负、带符号净战损与配对实际搜索收益，辅以区间覆盖率、校准及延迟。

生产训练数据前，按构筑族、机制族、敌人系列和独立公开根成组切分，禁止相邻牌数或私有世界副本跨训练和测试。记录每根的资格、失败原因、采样方式、支持和预算；保留超时与概率未解决质量。优先扩充实际敌人、卡牌协同、资源位置和跨回合压力；单独量化收集成本及长尾 unsupported 率。35 条现有条件仅提供开发检查。下一步应先验证部署使用的公开根采样和机制匹配，再开展有预算的最小学习对照。
