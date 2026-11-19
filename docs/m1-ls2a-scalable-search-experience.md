# M1-LS2A 规模化战斗与搜索经验生产

## 采样与根资格

独立宿主从原生 ModelDb 枚举角色及其卡池、起始牌、起始遗物、药水槽、各幕变体及遭遇。原生遗物和药水目录同时用于显示覆盖缺口。采样器按角色、幕、房型分层，在一个层内无放回遍历幕变体与遭遇，扫完后重排。正式普通／精英／首领权重为 5／2／1。卡组保留随机起始牌，从原生角色池选攻防骨架及其它常见、罕见、稀有牌，再按配置选规模、重复、升级。攻击类型和格挡变量来自原生静态元数据。卡池、升级、HP、资源、遭遇所属幕及真正进入战斗由引擎建根核验。合成策略保留空／起始遗物与既有合格药水，按允许的槽位装载，当前所有合成根标记自然可达性未知。

原生来源使用 D1/D2A 的实际游戏推进与合法菜单策略保全地图检查点、命令历史、局史祖先与入场动作。LS2A 对所选开放开发根用独立进程重新读档、检查候选节点和公开／精确入场状态。前缀历史及检查点摘要保存在审计 manifest；原始检查点留在原生来源目录。生成策略包含角色与种子、进阶、随机地图、奖励及商店策略。根是该策略实际存活后遇到的状态，入样概率未知。原生根进入独立的 `development` 分区。合成根按遭遇 ID 固定分配到训练、选模、测试，再检查完整配方、去升级组成、卡组家族、共享局史、配对种子及实际根摘要是否跨组。公开 LS1 报告配方和已知局史在采样准入时排除，历史 checkpoint 只从开放开发根读取。

N2E 资格独立于建根和模拟资格。已描述、部分及未知效果照 N2E 语义目录原样保存，未知效果包含 `UnsupportedEffect`。身份视图保留可见 ID、升级与有金额的公开修改。原生卡类型、目标、变量名和关键词独立作为静态元数据，变量名只用于可审计的覆盖标签。公开输入从原生当前战斗菜单提取，隐藏 RNG、抽牌顺序、未揭示意图、精确续体、回放和结局留在审计或标签侧。Solver 仍从精确原生状态忠实预测，本次所有搜索标签属于研究侧预测。原生根冷恢复等级、模拟执行资格、N2E 覆盖和 L3 标志独立保存。 [采样代码](../experiments/m1-ls2a/space.py) · [公开经验合同](../experiments/m1-ls2a/experience.schema.json)

## 分层搜索、持久化与导出

| 成本层 | 执行路径 | 正式上限 |
| --- | --- | ---: |
| 低成本 | Q1 预测单轨迹。记录合法动作序列、终局／中止、资源与热时间 | 48 |
| 标准 | 冻结 F3B C 四战略及修复。完整胜路由 F4 精确重建 | 128 |
| 高质量 | 同一根运行更高预算 F3B C，随后用 F4 剩余预算改进 | 256 |
| 候选 | 单独执行原 Q1、AGGRO、DEFENSIVE、ENGINE，验证完整胜路 | 每候选 96 |

Replay 上限包含付费重建。标准、高质量及候选先保留一半用于重建和可选改进。全部根先执行低成本层，原生根全部进入标准层。其它层通过预登记的哈希抽样分配。部分标准根在低成本轨迹未胜时继续升档。生产默认 F3B/F4 路径保持冻结。隔离宿主沿用 F3D-B 的中和定向兼容处理并验证撤除前后源状态一致，沿用 E3F 二进制校验。敌方侧终局带 E3 风险，不能作为本轮候选可靠标签。低成本较少转移和高质量较多转移均属于成本配置。

SQLite WAL 记录版本化 manifest、每根任务、原子完成结果、每次预算预约／结算和运行开销。记录以 Gzip 压缩。精确缓存以游戏／Solver／生产器版本、目录、完整合成 spec 或已校验的检查点与入场身份、策略和预算为键。读缓存验证记录校验和。恢复先收回上次仍在运行的任务，按其全额预约扣费，再按该根剩余重试次数排队。超时和传输故障至多两次尝试。原生边界不匹配与预测不支持入账。每个根使用独立原生进程。同一存储可新增具名冻结批次，明确新的命名空间和预登记预算。保留 SQLite、原生目录和 manifest 引用的检查点可重开批次。运行中的备份可通过 SQLite backup API 获取一致快照。数据集复核副本通过私有 manifest 摘要、Gzip 分片及 SHA-256 验证。

分片按分区保存公开输入和标签。读取器返回与 LS1 相同的 `(root, public, candidate, cap, utility)` 五元组，根摘要仅用于识别相关样本与缓存特征。可选择 Card ID、带缺失标记的 N2E 或仅完整 N2E 视图。候选状态的死亡或达到动作／转移预算可以作为有限预算下的零效用。墙钟中断、预测不支持和已知差分保留原始原因，排除出该监督目标。低成本预测死亡也仅描述该策略的轨迹。 [批量执行](../experiments/m1-ls2a/pipeline.py) · [存储](../experiments/m1-ls2a/store.py) · [训练导出](../experiments/m1-ls2a/export_data.py)

## 预算冻结与实测

一轮初探定位到进阶状态减少药水槽。修正槽位约束后，用同一批覆盖五角色、三幕和三类遭遇的 20 根比较 1 与 4 个 worker。两组所有精确根及策略语义结果一致，共计 1,029 Replay。端到端用时 66.5 s 与 10.9 s。4 worker 单进程峰值约 131 MiB，同时驻留总量峰值约 495 MiB，试跑目录约 3.0 MiB。两次均为小批单次实测，冷启动环境和任务组成会影响吞吐。

正式冻结 4 个 worker、1,000 个合成请求、45 个原生根、1,200 s 批累计墙钟、每根 65 s、225,000 Replay（含重试）、1,300 MiB 引擎总工作集和 650 MiB 运行目录。先执行 32 个任务，停在事务边界，再用相同 manifest 恢复。进程骤停时未完成 Replay 采用预约全额计费，墙钟累计来自已落盘的批次片段。活跃进程及时限可能造成小幅边界越过。 [试跑配置](../experiments/m1-ls2a/pilot.json) · [正式配置](../experiments/m1-ls2a/config.json) · [预算冻结](../experiments/m1-ls2a/budget-lock.json)

正式处理 1,045 个请求，产出 **1,031 个去重根**，其中 986 个合成根、45 个原生根。45 个原生根来自 15 条新局史、五角色各 9 根，均在第一幕。已有 D2A 原生采样和独立冷恢复耗时 33.8 s。LS2A 重建再次通过 45/45。合成请求中的 14 个失败均为第二幕 `KAISER_CRAB_BOSS`。两次独立复现均在合成入口直接返回 `card_reward`，没有形成可资格的活动战斗根。任务与原因全部保留。批次无传输重试，唯一根去重后没有重复；共有 1,028 个去升级配方与家族、1,001 个种子配对块。训练／选模／合成测试／原生开发分别为 613／138／235／45 根。

| 角色 | 根数 | 遭遇 | 命中角色池卡牌 |
| --- | ---: | ---: | ---: |
| Defect | 209 | 79 | 89/91 |
| Ironclad | 205 | 79 | 88/90 |
| Necrobinder | 200 | 79 | 89/91 |
| Regent | 211 | 79 | 89/91 |
| Silent | 206 | 79 | 89/91 |

覆盖目录中 79/80 个幕与遭遇组合、89 种可观察敌人。第一至三幕分别 379／318／334 根，普通／精英／首领分别 668／251／112 根。包含 448 个实际卡牌 ID，其中 444 个在 454 个原生角色池 ID 的并集，另外四个来自原生局史。覆盖 124 项静态机制／关键词标签、19 个遗物和 16 种药水。原生目录仍有 297 个遗物与 53 种药水未观察到，合成队列没有主动用药、非起始遗物、跨角色卡池填充或修改牌。原生局史出现的额外内容照实采集。牌组规模中位数 18，入场 HP 比例中位数 64.3%。上述覆盖率按身份和入场来源计算。

| 成本层 | 执行 | 胜路 | Replay | 单调用墙钟 P50 |
| --- | ---: | ---: | ---: | ---: |
| 低成本 | 1,031 | 217 条预测胜路 | 11,531 | 648 ms |
| 标准 | 451 | 132 条固定重建胜路 | 16,352 | 102 ms |
| 高质量 | 106 | 23 条固定重建胜路 | 10,364 | 103 ms |
| 独立候选 | 340（85 根） | 53 条固定重建胜路 | 5,048 | 33 ms |

低成本总有首个预测调用的冷开销，热 P50 为 199 ms。该层产生 276 条策略死亡、8 条截断、530 条不支持。整批中 552/1,031 个根在至少一条实际路线触及预测不支持或边界缺口，其中 AnyAlly／AllAllies 共 249 条，效果镜像不完整或缺失 271 条，另外 10 条为选择边界。编码方面，1,029 根至少有一张机制不完整牌，仍保留身份和可核实的静态元数据。正式采集使用冻结策略，学习模型为可选的下游消费者，模型缺失导致的任务失败为 0。整批未执行独立 L3 终局认证。按首条路径样本观察到的支持范围与原生规则一致性分别解释。

44 个根有两个以上可比较候选结果，其中 5 个的胜路发现有分歧。标准和高质量成对的 106 根中，高档新增 3 胜，20 个共同胜根有 8 个提高锁定 HP，最高 +8。低成本和高质量成对的 106 根中，17 个在两层都获胜，高档从低层的 5 次策略死亡及 1 次不支持中找到胜路。升档分配包含困难根，表中总体胜路率用于描述各层输出，配对项用于比较。

正式两个运行片段墙钟共 **644.1 s**，实际 43,295 Replay，约 **5,763 根/小时** 或 67.2 Replay/s。每根总时间 P50 2.04 s，原生初始化 P50 1.03 s。正式引擎并行驻留峰值约 512 MiB，单进程历史峰值约 138 MiB。运行目录约 89.5 MiB，SQLite 本体约 5.0 MiB，10 个压缩训练分片合计约 0.87 MiB。12 个用真实根和相同版本预算注册的缓存复核均命中，启动引擎数、Replay 扣费均为零。该吞吐包含原生冷建根及分层执行，原生局史采集耗时另列。

LS1 的输入堆叠和两个网络头均成功读取导出。共有 170 条候选监督记录，分区内可按相同根分组。小型拟合验证使用 31 个训练根的 105 条记录和 3 个选模根的 9 条记录，完成 Card ID 与带缺失标记的 N2E 两种拟合。合成测试和原生开发标签不进入此次拟合。拟合只验证接口，后续独立评价模型需要更多覆盖充分的选模与报告根。 [正式汇总、缺口及代表证据](../experiments/m1-ls2a/evidence.json)

下一阶段扩大训练时，优先补齐友方目标、关键选择和未覆盖效果镜像，并在代表性终局上独立做原生差分核验。扩大真实局史到第二、三幕，再按实际跑局分布补足药水、遗物、牌修改和高难度资源。模型侧同时利用 Card ID、可核实静态字段及 N2E 缺失标记，按搜索分歧和成本选择更有信息量的多预算根。

## 验证与复现

运行平台是 Windows、游戏 v0.113.1 / 26660232、CoreCLR 9.0.7、已资格 E3F Solver 0.51.5-e3f.1。隔离构建和原生 DLL 要求见 [项目状态](PROJECT_STATUS.md) 与 [E3F](m1-e3f-predator-terminal-fix.md)。未复制运行时、存档或大数据到 Git。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:OPENBLAS_NUM_THREADS = '1'
python -X utf8 experiments/m1-ls2a/build.py
python -X utf8 experiments/m1-d2a/build.py

foreach ($mode in 'serial','parallel') {
    $out = "logs/ls2a-qualified-$mode"
    $workers = if ($mode -eq 'serial') { 1 } else { 4 }
    python -X utf8 experiments/m1-ls2a/pipeline.py catalog $out
    python -X utf8 experiments/m1-ls2a/pipeline.py prepare $out --config experiments/m1-ls2a/pilot.json
    python -X utf8 experiments/m1-ls2a/pipeline.py run $out --workers $workers
}
$env:STS2_LS2A_PILOT = 'logs'
python -X utf8 -m unittest discover -s experiments/m1-ls2a -v

python -X utf8 experiments/m1-ls2a/pipeline.py catalog logs/ls2a-repro-production
python -X utf8 experiments/m1-ls2a/history_plan.py logs/ls2a-repro-production/catalog.json logs/ls2a-repro-history-plan.json --namespace ls2a-native-20261119
python -X utf8 experiments/m1-d1/bank.py sample logs/ls2a-repro-native --host m1-d2a-build --config logs/ls2a-repro-history-plan.json --workers 4
python -X utf8 experiments/m1-ls2a/pipeline.py prepare logs/ls2a-repro-production --history-bank logs/ls2a-repro-native
python -X utf8 experiments/m1-ls2a/pipeline.py run logs/ls2a-repro-production --workers 4 --max-new 32
python -X utf8 experiments/m1-ls2a/pipeline.py run logs/ls2a-repro-production --workers 4
python -X utf8 experiments/m1-ls2a/export_data.py logs/ls2a-repro-production logs/ls2a-repro-export
```

LS2A 定向 7 项、LS1 定向 5 项通过，覆盖跨进程根隔离、有效排列、关闭模型等价、字段白名单、预算误差、崩溃恢复、缓存校验和及分组泄漏检查。全量 1,031 条导出通过 JSON Schema、N2E 身份往返与机制视图一致性检查，各分片 SHA-256 校验通过。副本目录人为引入目录漂移后，冻结运行在启动引擎前拒绝。机制与 Card ID 拟合冒烟耗时 1.23 s。五角色全局跑局回归适用于生产规则变更，本次验证集中在隔离宿主与数据管线。

`pytest -q tests` 全量通过 162 项，另有 1 项既有跳过。S1 检查点合法出边少于两条，无法执行 A/B/A。
