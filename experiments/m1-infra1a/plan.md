# INFRA-1A 运行协议

起点 `6651a4ec14220abb581194240476c490c557b24d`。生产工作量、随机种子、权重、公开策略及准入沿用 0B。每个 treatment 单独启动一个 worker，按原根编号顺序运行。正式生产时间自 worker 启动至最后 gzip 完整关闭；统一计算账本采用整次子进程启动至退出的 wall，含输入检查、收据校验前的清理、构建、失败及开发验证。约 7,200 秒共用预算在安全边界检查；串行运行，原目录和 0B 账本只读。

1. 编译独立 5D 与 5E 批处理宿主。计量宿主与正式 DLL 分开。检查原源码校验和在各自冻结 PDB 中，并使用同一 Solver、Godot、游戏及规则。
2. 首先比较冻结自然根 154 与条件世界根 75 的完整规范记录和公开事件；用同一参考队列比较 G2 单样本与同一批已就绪输入的张量、分数、概率与排序。浮点不精确时保留原评价。
3. 原 5E 三个完整面板先进行只读影子调查。根、世界与方案编号只用于事后分组。搜索输入使用公开菜单、信念、约束、开局 HP 和完整公开动作史等字段。计时区分建键与 Planner 本身。详细指纹与输出记录归档开销保留在任务 wall。
4. 固定五组正式负载，先运行各组新原版和仅批处理候选，依工作量交错 A/B、B/A；预算允许再反向。需优先保留高预算自然和 5E 的完整产物及真正无详细插桩的端到端对照。全量逐行与 0B 归档核对，只去掉已有顶层耗时字段。额外资源优先于能确定下一工程方向的归因与反向重复。单次未完成 workload 单列。
5. 深度优先的条件方案递归可能先访问子孙、命中已访问路由或耗尽当前配额，保留冻结标量调用。FIFO 参考队列只取调用前已经排队的前缀，最大 32 个，并受剩余逻辑请求配额限制。宿主逐条使用原 Reference；分支退出后即固化公开回复。后产生的孩子全部在队尾以原顺序入队。遇到带观察回调的调用保留原函数。

## 复现

以在本机准备好 0B 输入和构建目录的独立工作树为起点。新执行使用空的 1A 输出目录与新账本。脚本拒绝覆盖同名产物；已验收的命名 treatment 可继续使用。宿主构建读取相应的 PDB 核验源码和此前离线还原源。以下命令在仓库根运行，只需为本次目的选择已列明的阶段。

```powershell
python -B experiments/m1-infra1a/build.py
python -B experiments/m1-infra1a/campaign1a.py smoke
python -B experiments/m1-infra1a/campaign1a.py shadow
python -B experiments/m1-infra1a/fixtures.py
python -B experiments/m1-infra1a/schedule.py primary
python -B experiments/m1-infra1a/schedule.py scores
python -B experiments/m1-infra1a/schedule.py reuse initial-dev
python -B experiments/m1-infra1a/schedule.py profile natural
python -B experiments/m1-infra1a/schedule.py reverse natural
python -B experiments/m1-infra1a/schedule.py attribution natural
python -B experiments/m1-infra1a/schedule.py cache-control initial-dev
python -B experiments/m1-infra1a/schedule.py cache-repeat initial-dev
python -B experiments/m1-infra1a/schedule.py cache-control audit
python -B experiments/m1-infra1a/schedule.py reuse audit initial-train
python -B experiments/m1-infra1a/schedule.py attribution audit
python -B experiments/m1-infra1a/schedule.py reverse initial-dev initial-train
python -B experiments/m1-infra1a/results.py
python -B experiments/m1-infra1a/host_report.py
python -B experiments/m1-infra1a/tables.py
python -B experiments/m1-infra1a/verify.py
```

原始运行顺序、每个命令的参数和包含启动/退出的预算收费以 `evidence/campaign.json` 为准。离线校验只需本仓库内的 1A 收据以及 0B 的冻结摘要和原版逐行压缩收据。
