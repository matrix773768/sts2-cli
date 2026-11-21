# II-H.3 原生宿主稳定化

起点为 `5043f95467ee88a9e41375c51278a651b93ad14d`，分支 `port/v0.113.1`。原生 STS2 v0.113.1 Build 26660232，CoreCLR 9.0.7。使用 II-H.2 Solver DLL 和 H.3 严格战斗认证。游戏 DLL SHA-256 为 `62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3`，Solver DLL SHA-256 为 `d15ba0e66d2bf54dd1d00714c39f7b8ecc26b9a5b35b79ceb64277d4fd4a54dd`，审计宿主 SHA-256 为 `46e219d54cfe74ba6a4dffa4b74a04cb738981f76445654266a06ec1ee7533fa`。

## 旧失败定位

旧 60 根的环境失败全部位于第二批。8 个审计失败为 `000008`、`000009`、`000010`、`000019`、`000020`、`000021`、`000022`、`000026`。它们通过了进程 ready 和 Solver 身份检查，以 `synthetic_start` 响应超时结束。抽查 stderr 显示模型库已注册 1,867 项。两个执行失败 `000016` 和 `000017` 已取得战斗根审计戳，随后在 `i1_n2_reset` 超时。历史日志没有记录这些进程被回收后的退出码。旧账本 SQLite `quick_check` 返回 `ok`。检查时未发现存活的 dotnet 或 Python 子进程。

已确认的直接原因是原生根或预测初始化超过 12 秒 RPC 窗口。未能从历史证据确定是哪一个原生命令或系统资源导致等待。受控并发未复现超时，无法据此断定竞争、CPU 饱和或死锁。该机报告 16 个逻辑处理器。定向探针中单宿主峰值工作集最高 120.5 MiB。历史运行缺少同时段 CPU、内存与句柄时间序列。原阈值保留。

## 生命周期修改

公共 `EngineClient` 使用同一个启动截止时间约束进程就绪和运行时证明，在固定 `STS2_DOTNET_VERSION` 时检查实际加载的补丁版本。stderr 结束立即唤醒运行时证明等待。失败日志增加活动阶段、PID 和当时的退出状态。正常、超时或拒绝运行时关闭后新增 `lifecycle.json`，记录最终退出码和 I/O 线程回收。现有超时强制回收路径继续使用。正式审计按套件分批运行，保持策略、根、动作预算和认证规则。

## 定向结果

- 修改前，十个旧失败根单 Worker 的原生根初始化均成功，最慢 3.17 秒。代表根 2 和 4 Worker 各 4/4 成功，最慢分别为 1.78 和 1.84 秒。
- 修改后，单 Worker 10/10 到达预测器活动状态，2 和 4 Worker 对照各 4/4 到达。最大根初始化耗时均约 2 秒，预测器阶段含关闭均低于 1 秒。18 个生命周期记录均为 CoreCLR 9.0.7、进程退出码 0、I/O 线程已结束。
- 模拟挂起后回收和错误 CoreCLR 补丁拒绝的新增测试通过。生命周期与运行时模块合计 10 项通过。单 Worker 初始化复验属于阶段探针，完整认证以逐根回归为准。

## 复现

从仓库根执行，使用新输出目录。完整回归使用各 suite 的原有输入和策略，`--workers` 控制宿主并发。每次命令完成后再启动下一条。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/m1-nosl3c-iih2-candidate'
$h = 'experiments/m1-nosl3c-iih3'
$l = @('logs/nosl3c-iic-random-final','logs/nosl3c-iid-release-independent','logs/nosl3c-iie-broad')
python experiments/m1-nosl3c-iih3-stabilization/probe.py logs/new-stable-probe logs/iih3-holdout-retry/training.sqlite --solver $s
python "$h/replay.py" logs/new-stable-archive @l --solver $s --workers 2
python "$h/train.py" logs/new-stable-pair16 --solver $s --suite pair16 --workers 2
python "$h/train.py" logs/new-stable-holdout --solver $s --suite holdout --workers 2
python "$h/train.py" logs/new-stable-cold --solver $s --suite e3-update --workers 2
python "$h/train.py" logs/new-stable-resume --solver $s --suite e3-update --workers 2 --through-update 1
python "$h/train.py" logs/new-stable-resume --solver $s --suite e3-update --workers 2
```

## 冻结回归与配对

冻结 65 条全部重放。38 条严格认证均为精确匹配，含 20 胜、18 死。原有 34 条及四条 E3 全部保留。五条实质差异、八条预测风险及十四条历史数据缺口保持原分类。缺口拆分为 10 条只有前缀、3 条无可重建路线，以及 1 条旧账本执行失败。

旧独立 16 根为 10/16，9 胜、1 死，与 H.3 的完整对照一致。仍有一个原生战斗回合超时、一个旧执行错误、两个不支持、一个实质差异，以及一个 E3 精确拒绝。旧战斗回合超时发生在已有根及动作之后，与本次定位的初始化超时不同。

[逐根配对与阶段探针](../experiments/m1-nosl3c-iih3-stabilization/evidence.json)

旧独立 60 根完整重跑为 **44/60**，27 胜、17 死。正常 HP 24/30，999 HP 20/30。旧 II-H.2 的 41 条准入全部保持，新增 E3 胜局为 `0:000005`、`0:000008`、`1:000000`。与 II-H.2 同根的 60 条采集轨迹均逐动作匹配公开观察、动作及行为 logp。

此前 10 条环境失败均取得真实分类，恢复六条旧准入 `1:000008`、`1:000009`、`1:000016`、`1:000019`、`1:000022`、`1:000026`。此前有完整采集记录的八条，与此前 H.3 的公开轨迹和 logp 一致。两条旧执行失败无完整轨迹可比，两条均与 II-H.2 的记录一致。正式配对未对单根做选择性重试。

| 仍拒绝的精确比较 | 首个差异 |
| --- | --- |
| `0:000006` | 第 18 个索引，手牌 H |
| `0:000020` | 第 2 个索引，合法菜单或动作 |
| `0:000023` | 第 9 个索引，死亡终局 Power |
| `1:000005` | 第 4 个索引，合法菜单或动作 |
| `1:000010` | 第 15 个索引，E3 历史计数 Y |
| `1:000017` | 第 17 个索引，合法菜单或动作 |
| `1:000020` | 第 17 个索引，E3 Power |
| `1:000021` | 第 20 个索引，E3 球状态 O |

其余 8 条由原标签拒绝，含 7 条预测不支持及 1 条达到动作预算。旧 60 根本轮无启动或执行层环境失败。

## v4 中断恢复

按同一配置完成两次冷跑更新，并从独立运行的第一次检查点恢复到第二次更新。两份账本身份相同，SQLite 完整性和根记录哈希检查均通过。32 条记录的结果、根、公开轨迹、资格、战损和行为 logp 一致。初始与两次更新的三个事务快照逐字节相同，覆盖模型、Adam 与 Torch RNG。逐步统计及模型哈希一致，最终模型 SHA-256 为 `8cc128a8a1fd74171a6fd8a23091ca2378f52979b4ab129cb557fb5e358ceb27`。

两次更新分别使用 10 和 11 条严格轨迹。第一批的 `000007`、`000012` 和第二批的 `000014` 为严格认证 E3 胜局。第一批 `000006` 和第二批 `000000` 的 E3 实差异仍被拒绝。行为 logp 最大复算误差为 `2.384185791015625e-07`。壁钟时间仍作为各次实验自身的诊断记录保留。

## 最终测试

固定 CoreCLR 9.0.7 后执行 `python -m pytest -q tests`，164 通过、1 跳过。唯一警告来自既有的未注册 `slow` 标记。复验结束时未观察到残留的 dotnet 进程，历史数据未作清理。
