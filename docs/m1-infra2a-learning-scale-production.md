# M1-INFRA-2A 自然与条件经验联合生产

CORE 主实验清单含 **4,096 个独立自然训练族**。原 945 个训练族、96 个开发族维持 5F 冻结顺序。2A 新增 3,164 个准入训练族和 179 个准入开发族，主实验使用前 3,151 个新增训练族，另有 13 个准入训练族可扩展。新旧合计 4,384 个准入自然族，其中训练 4,109，开发 275。每族一个自然种子。[冻结排序与主清单](../experiments/m1-infra2a/splits.json)

### 自然生产与族隔离

| 来源 | 尝试 | 准入 | 准入实际 C | 失败前缀 C | worker 分钟 | 公开导出秒 |
|---|---:|---:|---:|---:|---:|---:|
| train | 3400 | 3164 | 15359 | 662 | 57.51 | 59.65 |
| dev | 192 | 179 | 860 | 43 | 5.50 | 5.90 |

带完整公开观测的主集导出实测得到 4,096 行、19,936 个实际 C。新增准入自然训练与开发共有 16,219 个 C，合并 H5 两批的 5,089 个 C 后累计 21,308 个。

新增训练准入率 93.06%。3,400 个初始训练族、192 个开发来源族和 128 个后续备用族在生产前冻结。备用按冻结顺序每批 32 族，达到主规模即停止。生成使用 DC1 的 Ironclad 构筑方法和 CORE-5D 训练开局模板，基础、普通合成和协同合成共享固定 donor 循环。独立族键为排序后的卡牌 ID 多重集摘要。历史排除覆盖 DC1 完整池、CORE-4、5A–5F 输入面板、5D 扩展、H4 开放面板、H5 两批完整 cohort 及其桥接开局。5F 确认面板两个种子的构筑均已纳入。历史输入合计 2,608 个不同成分指纹。公开归档保留每个输入文件摘要及其排除指纹，校验逐族重算新牌组键并检查历史、训练、开发、备用的交集。[排重证据](../experiments/m1-infra2a/history.gz)

自然失败最常见的原因包括 policy/observation_outside_evaluated_program（119）、conditional_policy/realized_boundary_outside_law（46）、HotPiles.RemoveCard/direct_draw_pile_remove @ Play（44）、AddCard/random_insert_known_positions @ Play（23）、OUTRAGE/modified @ ResolveMovedCardInPlay（16）。发布保留所有失败的实际行动、公开观测和已到达的 C。开发来源池的 192 个尝试全部锁定开发身份。[逐任务失败、来源和成本](../experiments/m1-infra2a/ledger.json)

### 中盘根与配对

分配预先固定为 48/72/72 个章节槽、48 个代表性槽、144 个公开差异优先槽，128 个目标回合为 3–6。每槽按指定章节和分区内的族哈希顺序扫描到指定回合，验证稳定决策、可交换多类型牌袋。差异优先槽额外要求至少两种合法出牌的资源或效果特征，且预算 32 的公开候选中有不同首动作和不同预测值或支持数。没有最小效用差阈值。根上用预算 128 计算完整分布，第一案取冻结 V2 最高值。代表性槽取下一套不同分布，差异优先槽按能力、牌区与资源、敌方和 HP/格挡四类预测分布的差异数选配。实际扫描 500 个候选，选定 192 个独立根。9 个已选根来自后来被拒绝的自然任务。[选根、选案及复评预登记](../experiments/m1-infra2a/registration.json)

| 分层 | 主尝试槽 | 选到根 | 主准入 | 复评尝试 | 复评准入 |
|---|---:|---:|---:|---:|---:|
| all | 192 | 192 | 161 | 32 | 32 |
| train | 144 | 144 | 122 | 24 | 24 |
| dev | 48 | 48 | 39 | 8 | 8 |
| act-1 | 48 | 48 | 44 | 8 | 8 |
| act-2 | 72 | 72 | 66 | 14 | 14 |
| act-3 | 72 | 72 | 51 | 10 | 10 |
| representative | 48 | 48 | 39 | 10 | 10 |
| difference | 144 | 144 | 122 | 22 | 22 |
| turn-1 | 22 | 22 | 19 | 5 | 5 |
| turn-2 | 21 | 21 | 21 | 3 | 3 |
| turn-3 | 34 | 34 | 28 | 6 | 6 |
| turn-4 | 36 | 36 | 31 | 2 | 2 |
| turn-5 | 30 | 30 | 26 | 5 | 5 |
| turn-6 | 28 | 28 | 23 | 8 | 8 |
| turn-7 | 21 | 21 | 13 | 3 | 3 |

第 3–6 回合实际选中 128 根，其中 108 根完整准入。

恢复时逐步核对自然公开轨迹、牌实例、PileLaw 与合法菜单，按真实动作重建 G2 历史。原子待选按冻结模型补入确认。每根保存一次进程内 checkpoint，同一世界的双方从同一牌序和未来 RNG 开始。闭合方案、原概率、战略 C 和终局预测随根保存。每一侧均执行方案和冻结后缀。主协议严格准入 161/192（83.85%），对应 161 个原世界对和 644 个初始重排对。主准入原世界后缀实际 C 为 867，重排后缀为 3451。根内配对均值有 67 个非零，43 个根的差值随世界变化。主要拒绝类别为 law_or_execution_gap（22）、two distinct complete laws unavailable（9）。受阻的后缀侧中，72 次无法在实例级建立可交换世界，49 次实际观测越出已估值程序，7 次实际边界越出条件分布。一根可有多次侧失败。部分成功世界和两侧失败前缀保留在拒绝行。

复评按预登记排序取完整主根，额外 4 个重排使用独立种子区间，引用同一原世界和同一组选案。复评完整 32/32 根，合计 128 个准入重排对、755 个实际后缀 C。独立复评与初始四世界的根均值之差 RMSE 为 15.761 效用单位。每个根以方案一减方案二计算均值，开发复评沿用开发分区。原始世界、各重排差值、种子、任务关联和两个均值分别索引。[逐根世界与来源索引](../experiments/m1-infra2a/ledger.json)

### 预算与版本

前 48 个正式槽的准入为 41/48，有 16 个根均值非零、8 个根跨世界变化。该窗口花费 2.35 worker 分钟（含所分摊实际扫描时间），每个准入根 3.44 worker 秒。按窗口线性外推，192 个主槽约 9.40 分钟，连同 32 个复评槽约 10.96 分钟。实际主执行及复评分别 7.22、1.54 worker 分钟，整面板筛选 74.32 秒。后续按原登记顺序运行。[前 48 次成本与分层](../experiments/m1-infra2a/window48.json)

四个生产 worker 的自然分片、观测导出、条件筛选、条件执行和复评合计实测 **74.11 worker 分钟**。另为未独立计时的工程准备、导入失败与预检查计提 2 分钟，预算账本共 76.11/120 分钟。自然与配对 worker 内部报告的 Python＋Hot CPU 为 66.05 分钟，单进程 Python/Hot 峰值 RSS 分别为 384.3/161.8 MiB。自然、观测导出与条件执行区间并集为 19.47 分钟。CPU 与 RSS 仅覆盖已计量的两类生产进程，准备、发布后离线核验、文档和 Git 另计。

起点为 INFRA `7b0f21e4420d1ebf61e7103a874e77af3c8313c5`，只读 CORE 输入为 `0902c56e338e72a4e7f97ef5e9617151a909c91c`。实测 H5 宿主、战斗库、游戏、Godot、G2/V2 权重、生产源码和运行时字段与原 plan 一致。续战固定 tactical32、零裕量与未闭合参考直接 G2，策略 ID 为 `25740c4a3b29a5f378f6bd5723d3b594be6547a77e16b891e461bbf2bfcdcda7`，自然行为 ID 为 `51ed7db73b4d583c183d5a37bbcb6a2f3585bc73cd4cb931774fee46b8e32616`。主条件及复评各有独立的协议 ID，每条记录另带后缀行为 ID。所有记录为 `native_audit=not_run`。本轮模型训练及原生审核调用均为零。[发布索引](../experiments/m1-infra2a/release.json)

完整离线校验已逐条核对 3,592 次自然任务、192 次主条件任务和 32 次复评任务的身份与准入标签。对准入轨迹另逐步核验公开菜单，逐根检查世界种子、分区隔离和复评父任务。

### CORE 读取

在 INFRA 仓库根运行以下命令。主清单导出自动跨 H5 和 2A 连接准入族，`primary_rank` 为冻结排名。自然轨迹的 `states` 保留实际原始 C，`--public-views` 提供每次决策前的完整观测。条件的 `public_prefix` 和每侧 `steps` 已随行保存。通用读取器默认导出准入样本，添加 `--rejected` 可读取失败与部分世界。开发数据分别使用 `dev` 数据目录及条件的 `--split dev`。

```powershell
python -B experiments/m1-infra2a/verify.py
python -B experiments/m1-infra2a/read_primary.py --public-views --output logs/core-primary-4096.jsonl
python -B engine/HotSearch/read_experience.py experiments/m1-infra2a/train --split train --kind natural --public-views --output logs/2a-train.jsonl
python -B engine/HotSearch/read_experience.py experiments/m1-infra2a/dev --split dev --kind natural --public-views --output logs/2a-dev.jsonl
python -B engine/HotSearch/read_experience.py experiments/m1-infra2a/main --split train --kind conditional --output logs/2a-pairs-train.jsonl
python -B engine/HotSearch/read_experience.py experiments/m1-infra2a/main --split dev --kind conditional --output logs/2a-pairs-dev.jsonl
python -B engine/HotSearch/read_experience.py experiments/m1-infra2a/repeat --split dev --kind reassessment --output logs/2a-repeat-dev.jsonl
```

从干净输出目录复产时，依次运行本研究目录的 cohort2a.py、register.py、natural.py dev、natural.py train、natural.py reserve、paired.py、results2a.py 和 verify.py；需要相邻的冻结 CORE 工作树以及 H5 使用的本机游戏、宿主和模型依赖。已发布分片按任务身份及摘要复核后跳过。重复复评在独立分片中引用原始主任务。
