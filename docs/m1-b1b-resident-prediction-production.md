# M1-B1B 多遭遇常驻预测与人工数据生产

**常驻原生辅助建根在本样本保持低延迟。** 一个进程连续完成 24 根，以及逐根冷对照，预测与原生退役的逐步证据全部匹配。完整批次含首次启动、固定 F3B C、固定预算 F4、每根原生退役和进程退出。常驻 **1.77 根/秒**，逐根冷 **0.26 根/秒**，约 **6.77 倍**。24 根内未见后段延迟恶化，但工作集仍增长，长期驻留尚未验证。

基线为 `ed28ba7daa97fae9af1019e5a456c1a9db4df7c8`，`port/v0.113.1`。使用 Windows、SDK 10.0.404、本地 CoreCLR 9.0.7、游戏 v0.113.1／Build 26660232、冻结 CombatSolver 0.51.5。运行校验原生、Solver 与隔离宿主，版本及 SHA-256 保存在输出。样本仅取 F5A 已开放开发根，未打开验证或封存测试根。

## 样本与安全边界

[冻结输入](../experiments/m1-b1b/inputs.json) 有六个不同根，包含两个角色、第一与第二幕、四种普通遭遇、力量、自伤、防御和开场爆发构筑，有空槽、Flex Potion、Dexterity Potion、无遗物及起始遗物。分组在测量前固定。简单组为 `CORPSE_SLUGS_WEAK` 自伤和两个 `SHRINKER_BEETLE_WEAK` 构筑。复杂组为两个第二幕 `BOWLBUGS_WEAK` 和一个 `NIBBITS_WEAK`，用于覆盖多敌与猎杀者终局。分组是本样本的描述，未推广为通用难度分类。

先做跨角色、遭遇、幕数的 A→B→A（`24a989ab` → `44ffda5a` → `24a989ab`），通过后才开始六根顺序重复四轮。冷组顺序相同，每个根用独立进程。两组每根均执行相同搜寻和原生退役操作。根公开状态、原生战斗快照、身份、完整 run/player RNG 摘要、挂载后 profile、预测动作、逐步摘要、状态、战损、资源及转移逐根比较。性能时钟与进程工作集不参与语义哈希，跨进程 profile 只排除随机 `unique_id`。冷与常驻的原生退役完整帧哈希也逐根一致。

每根仍用原生单人局和普通遭遇入口建立新对象。沿 F3B 首胜合法退役至卡牌奖励，跳过奖励回地图，再释放捕获引用和战斗绑定。B1A/P1 重置检查队列、执行器、待决选择、奖励及任务均已清理，并解绑已登记事件和 selector 后恢复 profile。模型库、运行时及程序集保持热态，战斗 RNG 和对象每根新建。本轮比较能发现影响所观察状态的污染，未枚举 VM 内所有残留对象、缓存或监听器。

首轮试批对照误用了挂载后 profile 作为退役预期，有起始遗物的根已在挂载时改变该观察。门禁拒绝并关闭进程。修正后把退役结果与宿主保存的挂载前 profile 精确比较，挂载后的 profile 与同根冷对照单独比较。未绕过 fresh-process 或 P1 清理门禁。主动注入活跃重置、执行中取消和 12 秒 RPC 超时，三个进程均退出码 1 并丢弃。正常 24 根无失败、超时或进程更换。没有安全退役路线、活动帧差分或同根对照失配时，结果保留诊断，常驻批次停止，下一批从新进程开始。[三根试批](../experiments/m1-b1b/pilot.json.gz) · [故障证据](../experiments/m1-b1b/faults.json.gz)

## 成本与稳定性

以下为每根 P50／P90 毫秒。冷组各 12 个；常驻表排除首次启动根，简单 11、复杂 12。建根 RPC 包含模型初始化、输入、原生挂载和观察构造。全根墙钟从发出初始化请求到退役和核对结束，握手和最终进程回收另计入批次。百分位不相加。

| 阶段 | 冷 简单 | 冷 复杂 | 常驻 简单 | 常驻 复杂 |
| --- | ---: | ---: | ---: | ---: |
| 原生建根 RPC | 1,644／1,733 | 1,656／1,752 | 7.35／14.26 | 7.93／11.58 |
| 其中原生建根与观察 | 300／381 | 290／330 | 5.59／10.24 | 6.16／9.56 |
| F3B 预测准备 | 610／724 | 672／759 | 17.13／23.88 | 18.73／31.35 |
| F3B 热搜索 | 372／437 | 332／432 | 7.50／14.21 | 12.66／26.05 |
| F4 预测准备 | 20.47／38.87 | 21.99／64.11 | 13.03／28.56 | 14.68／23.65 |
| F4 热搜索 | 218／282 | 522／621 | 99.24／184.99 | 321.33／535.06 |
| 输入至预测完成 | 3,151／3,343 | 3,233／3,670 | 182／295 | 443／650 |
| 原生退役 | 343／385 | 370／497 | 67.61／110.92 | 112.72／181.32 |
| 全根墙钟 | 3,488／3,771 | 3,636／4,138 | 262／350 | 563／844 |

首次常驻握手 208 ms，原生建根 RPC 1,789 ms，全根 3,825 ms。冷批 91.98 秒；常驻批 13.58 秒。两批均有 24 个完整预测胜路，F4 16 个候选耗尽、8 个达到转移上限。两组均包含逐根合法退役，倍率不包含跳过 L3 的收益。另用生产模式运行六根加一个重复根，逐根写盘，7/7 完成，7.23 秒，约 0.97 根/秒，包含首次预热与文件落盘。该试运行和 24 根对照批的长度及写盘范围不同。

常驻后续 23 根的墙钟合计 9.50 秒。F3B 热搜索占 0.28 秒（3.0%），F4 占 5.11 秒（53.7%），两次预测准备共 0.82 秒（8.6%），原生退役占 2.21 秒（23.3%），原生建根 RPC 占 0.19 秒（2.0%）。剩余包括快照、通信和核对。进一步降低建根成本的同批上限较小，优先优化固定 F4 路径的每转移成本及原生退役开销。继续研究搜索分配时用质量配对验收，F5B 的四次／48 转移停搜保持关闭。

冷进程最高工作集约 131.9 MiB。常驻首根退役后为 123.8 MiB，末轮最高约 154.4 MiB。相同六根的第 2／4 轮，根墙钟 P50 为 290／262 ms、P90 为 827／443 ms。末轮未见延迟恶化，工作集上升约 30.5 MiB，尚未证明收敛或归因到托管分配与原生对象保留。证据支持有界批次使用，24 根之外的长期稳定性待测。[24 根冷／常驻记录](../experiments/m1-b1b/sequence.json.gz) · [分布表](../experiments/m1-b1b/summary.json)

## 预测生产合同

输入外层 `input_schema=1`，包含唯一 case ID、输入 spec、顺序和分组。基准模式额外要求匹配开放开发归档的 source_case。生产模式允许指定独立人工清单并核对批内重复根。当前 spec 必须提供 S2A schema 2 的 seed、角色、幕与幕变体、难度、遭遇、入场 HP/最大 HP、有序卡组及升级、遗物和药水槽。支持 Ironclad/Silent、第一和第二幕标准普通遭遇，原生验证模型、卡池、升级和遭遇所属幕。遗物限空或对应起始遗物，药水槽限空、Flex 或 Dexterity，搜索禁主动使用。额外 spec 字段、Neutralize 适配冲突和不支持的资源显式拒绝。其它模型机制仍可触发冻结 Solver 的 unsupported 或无胜路，原样记录。

输出外层 schema 1 固定游戏、宿主及 Solver 哈希、F3B C/F4 配置、512 共享转移上限及离线 RNG 使用。记录 schema 1 载有人工作业、根身份及 RNG 摘要、首胜和终选动作与逐步摘要、状态、终局 HP/最大 HP、累计战损、战斗金币和药水槽、F4 成本、原生退役诊断与异常。支持预算内保底；终选按同药水槽、最大终局 HP。金币与最大 HP 取预测战斗边界，奖励和跨房永久效果没有作额外预测。生产模式每根原子写出一个 `records/NNNN.json`，版本配置在同目录 `contract.json`，批次结果在 `results.json`。失败批次保留已写记录并返回非零状态。

记录使用 `synthetic=true`、`natural_reachability=unknown`、`evidence_level=prediction_only`。猎杀者结尾保留 E3 标记，应结合数据消费者的终局语义处理。本轮两个猎杀者根的首胜都有原生终局 stamp 差分，跨模式原始退役帧一致，活动步骤未见差分。终选另有风险标记。只用首胜退役，F4 终选具有本次预测证据。严格 L3 合同和历史标签未改变。

## 复现

在仓库根使用本地游戏、RitsuLib、CS1 基线 Solver 及 S2B 开发归档。各输出目录用新路径。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
python -X utf8 experiments/m1-b1b/build_probe.py
python -X utf8 experiments/m1-b1b/run_probe.py pilot logs/m1-b1b/pilot-repro
python -X utf8 experiments/m1-b1b/run_probe.py sequence logs/m1-b1b/sequence-repro
python -X utf8 experiments/m1-b1b/run_probe.py faults logs/m1-b1b/faults-repro
python -X utf8 experiments/m1-b1b/run_probe.py produce logs/m1-b1b/production-repro --input experiments/m1-b1b/inputs.json
python -X utf8 experiments/m1-b1b/summarize.py logs/m1-b1b/sequence-repro/results.json logs/m1-b1b/summary-repro.json
python -X utf8 -m pytest experiments/m1-b1b/test_resident_production.py experiments/m1-b1a/test_evidence.py experiments/m1-s1/test_synthetic.py -q
```

隔离构建、实机试批、连续批次、生产写盘、故障探针及 8 项定向测试通过。未运行全量 pytest 或五角色批次。
