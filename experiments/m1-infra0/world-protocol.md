# INFRA-0B 条件世界补充协议

生产版本为 CORE-5E 提交 `70e2e28b2915b962e93e3b30d3ec41aa5875fc6f`。5D 保留 0A 的 96 个自然世界和 44 个反事实任务。高档为 5C V2，5D 低档为同权重 V2low。正式机器上各 treatment 串行，只有固定总量扩展实验内部并行。

## 样本与分母

`world-panel.json` 在 5E 计时前冻结了训练 12 根、开发 6 根和独立复评 4 根。输入为原开放 train/dev 经验分片和原 audit12 分片。依归档的 source/index/family/seed 重建训练及开发视图，不生成确认集。默认生产仍读取完整 split、索引完整父轨迹；仅过滤外层原始任务编号。按历史世界数、无方案、错误及未匹配分层，层内以回合、前缀长度、同首动作和编号排序，在区间内等距取样。记录剩余自然前缀后的动作数作为续战长短的采样参考，真实续战工作量由本轮实测。冻结表包含每根已观察到的跳过原因。

审计编号直接来自原 16 个 audit12 根，取原 12 个高方差编号中排序后的首、中、末三个，并取原 4 个全零根的最小编号。生产执行仍对全部历史训练案例运行原 followup、重新 choose_root，再检查 public、首动作、标签及完整 law。训练/开发、估计/复评使用原 seed 命名空间，保持两个方案顺序和 4/8/12 世界规则。仅重排合法可交换的未知抽牌堆，其他随机流固定。每根共享一次初始候选选择。

记录尝试根、启动的世界、有两个返回的配对世界、两侧匹配且有终局效用的局部有效世界，以及完整根实际准入的世界。整组准入要求数量达到原配额且每个世界的两侧均合格。失败开销留在端到端分母；一个世界两侧有结果也可能整根被排除。5E 续战从 realize 的真实 fight 调用计数，无自然终局复用。计量版按根/世界/方案保存前缀建根、step、投影、重排字节、公开一致性检查、真实首回合执行、续战及 reset。单 world 的边际成本合并其两侧，错误根保留已发生的单侧成本。初始固定成本从根循环入口至第一个世界；无世界的根记至刷新。额外列出父轨迹扫描、审计选根、模型/宿主启动等整任务成本。嵌套耗时及两类进程 CPU 互不累加为 wall。

## 顺序与预算

使用约 7200 个累计 worker 秒的同一账本。先做原高档自然与反事实各一组 Baseline/Aggregate，再建 5E 独立计量宿主，执行一个 4 世界根的规范 JSON、公开动作与重排语义检查。正式 5E 初采和复评使用相同面板的 Baseline/Aggregate。先覆盖不同负载和 1/2/4 worker，再按预算逆序 Aggregate/Baseline 补交叉重复；单根极慢时可超出估算，到任务边界复核。若触发逐行差异，保留原始数据、定位首差，受影响的对比单列。预算不足不删根。0A 的计量合同及公开信息边界继续适用。

首遍从世界侧开始至 reset 统计模型推理。为区分 G2 首方案执行与后续 fight 的推理，反向 Aggregate 在已有 fight 包装器的入口与出口读取相同累计器的差值，对异常返回也记录。原始表通过 `suffix_inference` 字段区分两版。首次部署的计量源码摘要和最终源码摘要一并保留。两种测量均以同一冻结生产记录作精确对照。

2 worker 首遍出现高于线性的表观效率，4 worker 分片完成时间分散。在主要反向对照以及诊断完成后，若统一账本可预留完整一对，则补齐审计的 Aggregate/Baseline，并以 4→2 的逆序复核固定负载扩展。扩展的正式报告给出所有遍次和均值。加载 5D 原有多 split 容器时仅取 train/dev，augmentation 只取 dev2；用于 5E 的视图和准入全部由开放记录建立。

从已准备的独立 INFRA 工作树执行以下命令。使用空的 campaign 输出或归档另一次运行的独立工作树；构建与原始账本保留在本地 logs。联合入口继续同一账本。正式运行实际先调用 `campaign.py high`，再调用 `finish_campaign.py`，与联合入口使用同一执行路径。`closeout.py` 按剩余预算运行 12 世界审计面板的定向 Diagnostic 和三章原生重载。`verify_campaign.py` 校验工作树中的原始产物；携带 `--archive-only` 可直接校验提交内的证据包。

```powershell
python -B experiments/m1-infra0/world_assets.py ../sts2-cli
python -B experiments/m1-infra0/formal.py infra0b --combined
python -B experiments/m1-infra0/closeout.py
python -B experiments/m1-infra0/verify_campaign.py
pwsh -NoProfile -File experiments/m1-infra0/scaling_plot.ps1
```
