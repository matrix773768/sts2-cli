# M1-D1 原生战斗数据工厂

2026-11-18。基线 `a934a2638d07e3177714526202c46ef52d6bd0ad`，分支 `port/v0.113.1`。STS2 v0.113.1 / Build 26660232，Windows x64 / CoreCLR 9.0.7，冻结 CombatSolver 0.51.5。受测引擎、原生游戏 DLL、求解器和历史 JSONL 的 SHA-256 见公开索引。

**正式批次得到 45 个严格恢复的原生根，覆盖 8 条独立局史、8 个种子和 16 种遭遇。** 其中 5 个第二幕根来自同一条辅助局史。自然策略批量取得了多来源第一幕数据，独立的自然第二幕覆盖仍为零。双并发首次采集和严格恢复为 **42.94 个新根/分钟**，串行为 **15.72**。

[实际数据集索引](../experiments/m1-d1/dataset-index.json) · [机器可读吞吐](../experiments/m1-d1/throughput.json) · [清单 Schema](../experiments/m1-d1/manifest.schema.json) · [单根清单示例](../experiments/m1-d1/manifest.example.json)

## 采集与数据合同

- 配置指定角色、难度、游戏和策略种子、合法地图节点排序或随机选择、领取首项或跳过卡牌奖励、离开商店或购买最便宜的可支付在售牌。实际战斗使用冻结 F2 Q1+Choice。支持从已登记且可用的地图检查点续跑，续跑通过父局史与进入该房间前的动作前缀链接。归档来源只从版本化 `boss_reward_run_1.jsonl` 回放至原生 Boss 奖励。
- 每次入场先用 SearchEnv 的地图合同核对原生出边。在 MapRoom 写继续存档，再用原生节点动作进战。采集记录整份公开开局、含 RNG 的 live 延续摘要、永久资源、局史和构建身份。另起进程校验存档 SHA-256、完整地图和出边摘要、合法进入动作、完整公开开局、live 摘要及资源。退出前再次核对源字节。恢复范围限于已经审计的原生地图边界。
- 严格根 ID 由原生身份合同、构建与 live 摘要确定。每次出现先独立恢复，再按严格身份去重。相同局史的重复出现仍记录局史、进场命令位置和独立审计。已经登记的根由其首个合格出现持有存档。若严格身份跨局史碰撞，后出现的样本按结构化错误登记。场景、敌方组合、HP、药水、卡组规模和升级等可直接筛选；机制标签来自有限的卡牌与遗物 ID 规则，只表示出现线索。
- 起始角色、难度和种子确定局史。以种子稳定散列划分，六成开发、两成验证、两成测试作为散列规则，实际样本比例随种子变化。同种子的任何角色和难度也归同一集合。种子 `run_1` 固定为开发，历史前缀的三个分支均标记 `offline_teacher_assisted`。
- 本地 `manifest.json` 同时保存 RunRecord、CombatRoot、EvaluationRecord、RouteRecord、ValidationRecord 及出现关系。采样动作序列保留请求与已解析的战斗行动及选择。每个进场按边界建立 F1 观察，`resolved` 是审计注释。公开 `index.json` 派生自清单，包含筛选所需数据，原生存档、全量轨迹、进程日志和搜索逐帧证据留在本地 `logs/`。
- L0 是独立恢复的根，L1 是根上有冻结策略的原生胜负，L2 是完整预测胜路，L3 要有该路线独立原生差分通过且获胜的证据。L4 需要有明确干预、共有比较条件和同根的两条不同完整原生路线，经反事实审计后追加。本批没有 L4。评测与路线以新 ID 追加。策略记录原生 HP 账簿、起末资源、回合、原生动作与选择数量、分段时间和状态。手序的普通原生动作走通用 RPC，其独立 `execute_ms` 只覆盖有引擎计时的步骤。
- 采集进程与冷审计使用独立 profile 和有界 RPC。单写者锁下逐跑局原子替换清单，公开索引可从清单重建。批次中断后重做未提交局史，已提交局史跳过。损坏检查点在访问审计中移到本地隔离区，并标记该根当前不可用。磁盘上限按抽样扫描在命令边界停止，可有在途请求及原子写的少量超出。每局、每批有引擎期限，单战时间另在动作间检查。追加配置使用 `--extend`，要求原配置是新配置的前缀，可提高最大跑局数。

## 三阶段实测

启动试验使用铁甲战士 `run_1`、`run_2` 和静默猎手 `run_3`，外加从 `run_2` 首战前地图检查点继续的分支。8 次严格恢复，去重后 6 根。以 10 秒批次限额三次触发停止，第四次完成全部 4 个分支，得到同样的 6 根和 2 次重复。第五次重跑清单字节一致。另以 `--extend` 追加同一自然分支，增加 2 条出现记录，严格根保持 6 个。独立故障夹具篡改存档后审计拒绝，隔离文件和不可用标记均存在。

正式配置的 10 个分支中，3 个辅助分支来自同一局史，7 个自然分支各来自独立种子。自然分支 5 个第一幕死亡，2 个停于 `unknown_or_repeated_request` 原生选牌回调。自然分支 0/7 到第二幕，全部分支 3/10 到第二幕，按独立局史计 1/8。第三幕样本和通关均为 0。辅助根逐项匹配 F3A 的完整公开开局及 live 身份。

| 指标 | 数量 |
| --- | --- |
| 合法入场候选、冷审计通过、严格去重根 | 46 / 46 / 45 |
| 第一幕、第二幕 | 40 / 5 |
| 铁甲战士、静默猎手 | 28 / 17 |
| 普通、精英、Boss | 39 / 5 / 1 |
| development 根 / 局史 | 17 / 3 |
| validation 根 / 局史 | 20 / 4 |
| test 根 / 局史 | 8 / 1 |
| 机制线索 | 弃牌 17，回顶 14，过牌 9，能量或费用 6，战斗成长 5，永久成长 5，生命消耗 4 |

正式批次每根各跑两种廉价策略，各 45 次。手序 35 胜、10 死。Q1+Choice 35 胜、8 死、2 次未支持。原生死亡是正常结局。两个回调未支持被保留为非胜负标签。批次采样和首轮标签中执行故障、超时均为 0。策略评测 P50 端到端为 2.82 s / 2.95 s（手序 / Q1），其中冷根准备 P50 约 2.47 s / 2.50 s。完整战损与资源结果见索引。三个独立来源各复验一次开局，再逐根复跑两种策略，恢复 3/3，动作、回调、胜负、回合、战损及资源一致 6/6。含附加复跑共计 96 条廉价策略记录。

F3B 使用原有搜索与严格原生重放入口。自然采集的 `b01e6136fa2e`（第一幕）在 128 档、禁用药水时 14 次预测转移首次胜利，14/14 原生动作相等。开发根 `cc2b306131b2`（第二幕）在同档允许用药时 24 次转移首次胜利，17/17 原生动作相等。两次均使用预测器内部 RNG。两个根已按 L3 收录，其余 43 根为 L1。历史 F3B 批处理继续固定其冻结根，本阶段的 `label_f3b.py` 对 D1 根使用同一套引擎评测合同。高预算 CombatSolver 可以消费同样的地图检查点、入场动作和 F3A 根字段，并沿用 RouteRecord 与 ValidationRecord 追加。本批未执行该高预算标注。

## 冷吞吐与热探针

| 采集并发 | 端到端秒 | 合法候选/分 | 新严格根/分 | 第二幕及以后根/分 | 原生终局/分 | 并发进程峰值 MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 171.71 | 16.07 | 15.72 | 1.75 | 2.80 | 233.1 |
| 2 | 62.88 | 43.89 | 42.94 | 4.77 | 7.63 | 454.4 |

两批各自真实生成 46 次入场并严格核对。两批的 45 个根、逐跑局已执行动作、结果、地图摘要和划分逐项相同。内存为同时活跃引擎进程采样总和，包括采集进程和正在审计的子进程。每档一次、双并发先跑，冷初始化和主机状态随批次变化，2.73 倍是实测比值。90 条首轮标签累计约 244.86 s（串行），单独于采样吞吐计量。

冷审计 P50 串行 2.49 s、双并发 1.72 s。其中 `load_save` 请求 P50 为 1.96 s / 1.35 s，握手 P50 为 0.21 s / 0.14 s。双并发采样所有 Q1 步骤累计 4.19 s RPC，含 2.58 s 原生动作调用、0.43 s 战术观察、0.017 s 策略计算和 1.17 s 余项。基础采集的教师求解成本为 0。采集用时首先由冷恢复吞掉；第二幕产量由第一幕可达性主导。

独立计时构建在同一试采配置的 6 个严格根上复核了无探针身份和完整开局。80 次 Q1 步骤合计 2,057 ms RPC，其中引擎分发 1,727 ms（含公开战斗观察构造 348 ms）、响应 JSON 序列化 165 ms、stdout 写入与 flush 32 ms、剩余 134 ms。余项包含管道接收、Python 编解码、日志及调度。探针对其他命令也记录了上述阶段，细项在 `metered_pilot`。正式批次采用无探针构建。

独立重跑 M1-P1 的已验证固定地图脚本。冷分支总时间中位数 1,885 ms，热逐步 218 ms，热批量 135 ms；恢复区间分别为 1,451、19.7、14.5 ms。12 次已知边界复用通过冷差分，核对地图、逐步决策、RNG、profile 进度和结算存档。4 种故障均丢弃进程，包括非法动作、差分失败、超时和真实待完成选择。探针覆盖两条脚本、每个 worker 三次分支，峰值工作集 118 MiB。D1 对跨根长生命周期复用缺乏状态清理和内存增长的证据，因此批量采样使用冷路径。固定脚本吞吐未计入新根速率。

优先扩展可跨第一幕的合法局史。可先把阻断的两个选择回调补为单独的原生兼容实验，随后预先选择多个独立种子，离线有界辅助获得更多第一幕获胜通路，原样保留来源标签。热优化可放在已覆盖的局史类型有更多差分证据之后。未来如接入 Spire Codex、RunReplays 或 STS2 Runs，可以先把外部行为轨迹放入独立数据集，按当前版本独立原生重放并形成地图检查点与身份核对后才纳入严格根。

## 复现

在仓库根执行。预先按 [项目环境](PROJECT_STATUS.md) 配置本地游戏 DLL、CoreCLR 9.0.7 和固定 CombatSolver。启动三组采集时使用新输出目录；对同一目录使用原配置可恢复未完成局史。搜索和策略复跑需指定根 ID 或唯一前缀。

```powershell
python -X utf8 experiments/m1-f3b/build.py
python -X utf8 experiments/m1-d1/bank.py sample logs/d1-pilot --config experiments/m1-d1/pilot.json --workers 2
python -X utf8 experiments/m1-d1/bank.py sample logs/d1-w2 --config experiments/m1-d1/batch.json --workers 2
python -X utf8 experiments/m1-d1/bank.py sample logs/d1-w1 --config experiments/m1-d1/batch.json --workers 1
python -X utf8 experiments/m1-d1/bank.py evaluate logs/d1-w2
$roots = (Get-Content -Raw logs/d1-w2/index.json | ConvertFrom-Json).roots
$archived = ($roots | Where-Object { $_.run_id -eq 'archive-west' -and $_.context.floor -eq 3 }).id
$iron = ($roots | Where-Object { $_.run_id -eq 'iron-2' -and $_.context.floor -eq 2 }).id
$silent = ($roots | Where-Object { $_.run_id -eq 'silent-5' -and $_.context.floor -eq 2 }).id
python -X utf8 experiments/m1-d1/bank.py audit logs/d1-w2 --root $archived --root $iron --root $silent
python -X utf8 experiments/m1-d1/bank.py evaluate logs/d1-w2 --root $archived --root $iron --root $silent --repeat
python -X utf8 experiments/m1-d1/label_f3b.py logs/d1-w2 $iron --cap 128
python -X utf8 experiments/m1-d1/label_f3b.py logs/d1-w2 $archived --cap 128 --potions
python -X utf8 experiments/m1-d1/build_meter.py
python -X utf8 experiments/m1-d1/bank.py sample logs/d1-meter --config experiments/m1-d1/pilot.json --host m1-d1-meter-build
$checkpoint = (Get-ChildItem logs/m1-b2-benchmark/checkpoints/*.save).FullName
python -X utf8 scripts/m1_p1/run_probe.py logs/m1-b2-benchmark/summary.json $checkpoint logs/d1-hot
python -X utf8 experiments/m1-d1/throughput.py logs/d1-w1 logs/d1-w2 logs/d1-hot/results.json logs/d1-throughput.json --meter logs/d1-meter
```

若重编译导致 Headless 二进制哈希变化，根 ID 前缀随之变化。可在新索引中按 `run_id`、层、遭遇和 `live` 找到对应根。热探针需先按 M1-P1 的说明构建探针和准备对应 B2 检查点。

## 工程验收

隔离计时构建 0 错误、7 条既有 GodotStubs 警告。Python 编译、正式清单和示例的 Schema 校验、公开索引标签分层、实际商店购买、原生根差分、损坏隔离和 `git diff --check` 通过。固定宿主和计时宿主均使用本地合法游戏 DLL。

仓库 `pytest tests` 首次执行 157 通过、1 跳过、5 个探针环境错误。配置可写的 .NET 目录并把包含 CoreCLR 9.0.7 的本地 SDK 放到 PATH 首位后，原五个探针定向重跑全部通过。合计覆盖 162 个通过用例、1 个跳过用例，跳过原因是旧 S1 仅有一个合法后继。初次无目录参数的 pytest 收集到了 `logs/` 下的历史和外部代码，正式执行范围为仓库 `tests/`。五角色各五局兼容性批次未重跑，本阶段的代码和计时插桩只在隔离实验路径生效。
