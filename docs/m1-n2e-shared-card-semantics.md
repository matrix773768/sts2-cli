# M1-N2E 共享卡牌机制表示与数据合同

本阶段交付一套供战斗手牌与局外卡组共用的机制表示。作用节点保留顺序、目标、次数及触发关系，静态数值和公开动态预览各有来源。实现位于 [experiments/m1-n2e](../experiments/m1-n2e/)，由后续研究代码显式调用。

## 规则来源与资格

[原生提取程序](../experiments/m1-n2e/StaticCards.cs)在隔离 headless 宿主中读取游戏程序集的 ModelDb。每张牌独立克隆，记录费用、X 费标志、类型、稀有度、目标、关键字及 DynamicVars.BaseValue，然后沿原生 UpgradeInternal 和 FinalizeUpgradeInternal 提取升级版本。原始读数保存在 [static-evidence.json](../experiments/m1-n2e/static-evidence.json)。角色归属采用受测名单，Shiv 归入静默猎手数据组，供生成牌关联。

[机制映射](../experiments/m1-n2e/build_catalog.py)用原生变量填充节点，并用各卡的[官方规则文本](../localization_eng/cards.json)交叉核对效果、可见顺序和固定常数。例如猎杀者下回合抽 2 张来自规则文本，CombatSolver 的 CardEffectSpecRegistry 也登记了该延迟效果。CombatSolver 的 Power 镜像与原生复放为特定机制提供补充证据。它们覆盖可预测行为的一部分，CardEffectSpecRegistry 主要记录 Power 相关效果。

原生 CardModel 提供元数据及变量，出牌和 Power hook 仍由程序控制流执行。变量名无法给出变量消费顺序、是否跳过节点、触发栈、伤害属性、快照时机或选择边界。第一版用小范围结构化映射表达可核实的声明式语义。N2A.1 的公开 DTO 将目标、Power 和即时预览绑定到当前合法动作，相关来源是 [PublicInteraction.cs](../experiments/m1-n2a1/PublicInteraction.cs)、[N2A.1 原生核验](../experiments/m1-n2a1/native-audit.json)及 [N2D 原生核验](../experiments/m1-n2d/native-audit.json)。预览中的伤害与格挡来自受限镜像，抽牌字段读取受测牌的即时请求张数。实际抽到的张数还受牌堆及手牌容量等规则影响。

## 覆盖矩阵

表中的动态字段指 N2A.1 允许发布的预览字段。伤害预览需要当前合法目标。当前费用由合法菜单独立提供。每张牌的具体来源键、基础／升级节点和缺口标记见 [cards.json](../experiments/m1-n2e/cards.json)。

| 卡牌 ID | 静态资格及主要机制 | 公开预览 |
| --- | --- | --- |
| STRIKE_IRONCLAD、STRIKE_SILENT、SLICE、SHIV | 已描述。单段攻击，Shiv 家族与消耗 | 每段伤害、段数 |
| DEFEND_IRONCLAD、DEFEND_SILENT | 已描述。即时格挡 | 格挡 |
| BASH | 已描述。伤害后施加易伤 | 每段伤害、段数 |
| TWIN_STRIKE | 已描述。两段攻击，共用逐段力量修饰 | 每段伤害、段数 |
| INFLAME、FOOTWORK | 已描述。战斗内力量／敏捷成长 | 缺失 |
| POMMEL_STRIKE | 已描述。攻击后抽牌，升级改变抽牌数 | 每段伤害、段数、抽牌请求 |
| SHRUG_IT_OFF | 已描述。格挡后抽牌 | 格挡、抽牌请求 |
| FLAME_BARRIER | 部分。即时格挡和本回合受攻击反伤，hook 细节待核实 | 格挡 |
| IRON_WAVE | 已描述。格挡后攻击 | 伤害、格挡均缺失 |
| SURVIVOR | 部分。格挡后公开选择弃一张，选择边界的完整语义待核实 | 格挡、独立公开选择菜单 |
| BLADE_DANCE | 已描述。向手牌生成 Shiv，出牌清理时消耗 | 缺失 |
| ACCURACY | 已描述。战斗内 Shiv 家族伤害增益 | 缺失 |
| DODGE_AND_ROLL | 部分。即时格挡和次回合格挡，延迟量的快照和 hook 细节待核实 | 即时格挡 |
| BACKFLIP | 已描述。即时格挡后抽牌 | 格挡、抽牌均缺失 |
| CLOAK_AND_DAGGER | 已描述。格挡后生成 Shiv | 缺失 |
| PREDATOR | 部分。攻击后次回合抽牌，击杀终局的预测／原生续体存在已知差分 | 伤害、抽牌均缺失 |
| LEG_SWEEP | 已描述。先施加虚弱再获得格挡 | 缺失 |

22 张卡中 18 张达到本版静态描述范围，4 张保留显式 UnsupportedEffect。原生元数据覆盖 44 个版本。公开动态资格沿用历史受测字段及状态。完整行动执行、Power 生命周期和 L3 仍按原生轨迹逐项核对。诸如手牌溢出、目标死亡后的命令行为、复杂叠层、附魔的实际规则效果、随机生成和多步条件控制流仍需扩展或单独核验。合同预留 GainEnergy 和 ConditionalEffect，本卡池没有实例。受测升级覆盖效果变化，本批 22 张的基础费用在升级时均保持一致。

## 编码、绑定与合法信息

- **CardSpec。** 每个 ID 具有静态规则版本、来源、资格与升级变体。变体包含费用、目标、关键字及有序节点。节点按类别携带数值、次数、目标、持续期、触发条件或嵌套效果。未知卡与未知升级的数值为 null，机制为显式 UnsupportedEffect。静态语义只表达规则关系，后续学习器据上下文估计价值。
- **CardInstance。** 保存 spec_ref、upgrade_level、永久／公开修改三元组以及可选局部 occurrence_id。修改元组形状为 kind、公开规则 ID、整数值，由合法调用方提供。N2A.1 当前手牌 DTO 仅提供槽位、卡名与升级，适配器将实例修改标记为缺失。已有公开修改可以直接经 CardInstance 编码。选择、弃置、升级和移除由引擎执行，下一菜单以新 DTO 重新绑定。
- **CardContext。** encode_card_context 接收已解码的 N2A.1 Observation，返回学习数据与平行的菜单绑定列表。逐动作包含公开费用、合法目标、当前目标 HP／格挡／来袭段／允许发布的 Power、目标相关预览及缺失列表。手牌保留不可出牌的实例。绑定保留 action、hand、target、choice 索引，弃牌候选有自己的索引域。完全相同的候选机理相同，执行器仍能按菜单索引区分。绑定生命周期仅限当前菜单。隐藏 RNG、抽牌顺序、未揭示敌招、未来事件、私有续体及标签都留在接口之外。
- **DeckSpec。** 角色与卡牌多重集经稳定 JSON 排序，同 ID、同升级且同永久修改才在身份视图计为同一组。机制视图可以聚合同语义实例。内容摘要基于身份多重集、角色、完整性、规则版本和目录摘要，两种模式共享该摘要。来源枚举为 offline_root、visible_deck、public_history。完整性由调用方按观察范围标注。接口接收卡列表，排序后只表示组成，牌堆实际顺序及临时修改不进入卡组合同。可由规范身份视图重新构造 DeckSpec 并校验摘要。
- **模型输入。** [JSON Schema](../experiments/m1-n2e/schema.json)覆盖静态定义、实例、卡组、上下文与绑定。[编码示例](../experiments/m1-n2e/example.json)给出同一多重集的身份及机制视图。集合模型可展开 count 得到长度 N 的实例轴，或用计数加权汇聚。效果轴是每张牌的有序变长序列，可填充并给定 effect_mask；手牌、卡组和动作轴各有自己的有效位掩码。动态缺失以 null 和 missing_fields 双重表达，数值零仍是有效观测。训练张量排除版本、摘要、来源及操作绑定等审计字段。身份视图保留 ID、升级和公开修改，机制视图以结构化节点表达共性。例如基础攻击与双重打击共享 Damage，次数有区别；准确、生成节点和 Shiv 共享家族标签。

## N2F 实验设计

首个任务是预测冻结战斗策略下的遭遇胜率及胜利条件下的终局资源。评价对象是一场遭遇。首轮用 N2C 的 [initial-mean](../experiments/m1-n2c/models.json)及 [15 维公开策略](../experiments/m1-n2b/policy.py)，锁定策略、动作上限、药水规则和每根单轨迹预算。

1. **输入。** 样本输入包含 DeckSpec、角色、入场当前及最大 HP、难度、幕、合法可见的遭遇 ID、遗物与药水槽。给身份和机制模型相同的入场条件。根据输入时点审计遭遇是否可见。
2. **版本。** 实验清单固定游戏版本及 DLL 摘要、CombatSolver 构建及摘要、隔离宿主摘要、CoreCLR、策略代码和参数摘要、卡牌 schema/catalog 摘要、建根协议与数据快照。
3. **标签。** 以固定策略执行正常终局的 rollout 提供胜负、胜局终局 HP 或归一化 HP，以及已执行并可观测的药水等资源字段。预测与原生抽样逐条记录资格。额外奖励系统只有实际推进并验收才产生标签。
4. **分组。** 用组成摘要、构筑家族、共享局史祖先、种子/配对块和遭遇记录相关性；以构筑家族为主分组，跨集合共同祖先或 RNG 配对块放入同组或剔除。开发样本先确定模型及切分规则。报告独立新种子同构筑、同牌表的新组合和新构筑家族结果。
5. **组合留出。** 留出整组配方和其近邻改牌臂，避免同一组合的升级或改一张版本跨集合。显式测试组成牌在训练中分别出现过、组合关系整体未见的情况。首次评测前冻结留出清单、族规则和距离阈值。
6. **配对。** 在离线账本记录根、合成或自然来源、种子配对块、开局 RNG 对齐审计、抽牌观测差异和卡组干预。共同种子只用于离线配对和不确定性分析。同一配对当作簇进行 bootstrap。配对后续 RNG 可以随动作分叉。
7. **指标。** 胜负用 Brier、log loss、校准曲线并按家族／遭遇切片。胜局 HP 用 MAE、RMSE 及校准，带簇级置信区间。并列给出正常终局覆盖率、胜标签数、资源观测率。报告每例特征准备与单例推理 P50/P95、吞吐、内存和模型参数量。
8. **缺失和资格。** 超时、不支持、构建失败及可能影响标签的已知差分附原因与掩码。训练与评价按预注册的有效标签规则处理缺失，显式报告覆盖率及缺失集中在哪些构筑。原生差分审计和标签来源字段只进入离线账本。
9. **对照。** 比较简单卡组统计、ID embedding、机制 Deep Sets 和小型 Attention。身份与机制应有容量匹配的同架构对照，在相同划分、初始化次数、预算和评价协议下测量。先检查机制表示是否改善未见组合的泛化。
10. **冻结策略偏差。** 标签估计的是 initial-mean 驾驶下的结果。如果它不会利用次回合收益、成长、Shiv 或弃牌机制，标签会低估相应构筑的潜力。按机制家族审计行为和剩余资源，后续可用第二条冻结策略在少量成对开发根做灵敏度分析。

## 验证与复现

基线提交为 ba36decc623c6b6499e7f1b6c34a2663f0953341。原生构建 0.113.1/26660232 的 DLL SHA-256 为 62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3，CoreCLR 9.0.7。静态提取宿主使用 M1-I1 构建锁定的 CombatSolver 装配，SHA-256 为 d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13。公开动态证据来自 N2A.1/N2D 的 0.51.5-e3f.1，SHA-256 为 cea50e9570edbed06c7f0502fdc5949ba3846ee64605f4891b32768b4ef3d51c。机制目录规范内容摘要为 5c769c2102e7d9ae6c0543facf301180898732592dbbfa96f3b6beedb674af72。英语规则文本文件 SHA-256 为 229011ec27e2d0bad8f8483c2cdf4d9edc1ca79ce11dd5d5f4b4e43ee6678768。

原生静态重新提取与提交的 44 条版本读数一致。6 项接口测试通过，Python schema 测试因缺少 jsonschema 跳过，另用 PowerShell Test-Json 验证了全部 22 个 CardSpec 和 6 个示例对象。覆盖了稳定性、版本变动、升级、重复和不同公开修改、缺失预览、目标及弃牌绑定和身份卡组往返。此次验证范围为静态提取与共享接口，完整 pytest、五角色通关和新的原生战斗轨迹未运行。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
python -X utf8 experiments/m1-n2e/extract.py logs/m1-n2e-static-repro.json
python -X utf8 experiments/m1-n2e/build_catalog.py
python -X utf8 -m unittest discover -s experiments/m1-n2e -v

$cards = Get-Content experiments/m1-n2e/cards.json -Raw | ConvertFrom-Json -AsHashtable
foreach ($card in $cards.cards) {
    $card.schema = 'sts2.card-semantics.v1'
    $card.rule_version = $cards.game_dll_sha256
    $card | ConvertTo-Json -Depth 100 -Compress | Test-Json -SchemaFile experiments/m1-n2e/schema.json
}
$example = Get-Content experiments/m1-n2e/example.json -Raw | ConvertFrom-Json -AsHashtable
foreach ($payload in @($example.card_spec, $example.identity_deck, $example.mechanics_deck, $example.context) + $example.bindings) {
    $payload | ConvertTo-Json -Depth 100 -Compress | Test-Json -SchemaFile experiments/m1-n2e/schema.json
}
```
