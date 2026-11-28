# HotSearch

HotSearch 是 INFRA 独立研究生产器。一个 .NET 9 进程持有真实战斗，每个战斗只从游戏导入一次开局。Python 在公开决策点运行冻结 G2，在抽牌前 C 上批量运行冻结 V2，并写入研究数据。默认自然生产在已选策略的公开后继不属于预测分布时停止该根，保留前缀和原因。

## INFRA-1H5 常规研究生产

战术 32 是低成本研究行为策略。常规准入要求完整终局、合法动作与公开观察绑定、条件程序忠实执行和完整概率记账。条件世界按根准入，原世界及所有预定重排世界的两侧均须完成。未运行原生审核的记录带 `native_audit="not_run"`、空收据。失败保留实际前缀和原因，可在独立分区查询。修正 1A 仍是正式生产默认。

从仓库根目录运行。已交付的数据直接使用读取命令。新采集请使用独立的数据和工作目录；恢复同一采集时保持构建、输入、源码及分片大小不变。

```powershell
$env:HOTSEARCH_BUILD='logs/hotsearch-h5-local'
python -B engine/HotSearch/build.py
python -B engine/HotSearch/produce_batch.py experiments/m1-infra1h5/cohort.json.gz logs/my-h5-library logs/my-h5-workers logs/hotsearch-h5-local --workers 4 --size 16
python -B engine/HotSearch/read_experience.py experiments/m1-infra1h5/data --split train --kind natural --output logs/h5-natural-training.jsonl
```

交付包含首批 `experiments/m1-infra1h5/data` 和单独冻结的千场容量批次 `experiments/m1-infra1h5/capacity`。两批训练自然经验共享战术 32，构筑族互斥。需要每次行动前的完整公开事实、动作或待选菜单时，读取命令加 `--public-views`。新生产可执行 `python -B engine/HotSearch/publish_views.py DATA WORK` 从已提交 worker 的实际公开回复导出这一层；它绑定已封存数据集摘要。

同一生产命令可恢复未提交的分片。`--max-shards` 支持分阶段运行，`--retries` 控制基础设施失败的重试次数。已完成的规则失败占用其原分母。要检索条件监督，可使用 `--kind conditional`。还支持 `--family`、`--policy`、`--mechanism`、`--native` 和显式的 `--rejected`。程序入口、已冻结的数据清单和统计见 [1H5 报告](../../docs/m1-infra1h5-production-qualification.md)。

## INFRA-1H4 历史研究入口

自然生产可选 `--arm tactical` 或 `--arm contingent`。前者为所有合法首动作构造轻量、偏防御、偏成长和提前结束四类续法。后者增加待选策略，并尝试按同一公开观察组合闭合续法。`--limit` 对每个首动作和续法分别计量物理规则调用。只有所比较双方的条件质量均闭合，且期望提升超过 `--margin`，才干预。参考未闭合时运行直接 G2。每个闭合程序绑定父节点、公开菜单摘要和动作索引，实际轨迹保存动作绑定与完整边界分布。

```powershell
$env:HOTSEARCH_BUILD='logs/hotsearch-h4-public-fix'
python -B engine/HotSearch/build.py
$env:HOTSEARCH_ORACLE_MATH='1'
$env:HOTSEARCH_ORACLE_SCENE='1'
$env:HOTSEARCH_ORACLE_DIR=(Join-Path (Get-Location) 'logs/hotsearch-h4-release-oracle')
python -B engine/HotSearch/build_oracle.py
python -B engine/HotSearch/hot_produce.py logs/my-h4-production --arm tactical --limit 32 --margin 0
python -B engine/HotSearch/native_audit.py logs/my-h4-native logs/my-h4-production/natural.jsonl.gz
python -B engine/HotSearch/condition.py logs/my-h4-123 --ids 123 --arm contingent --limit 128 --suffix-limit 32 --audit --native-worlds 2
python -B experiments/m1-infra1h4/verify.py
```

`HOTSEARCH_ORACLE_MATH=1` 可在原生审核构建时补齐离线 Godot 数学接口。另设 `HOTSEARCH_ORACLE_SCENE=1` 可补齐可见性与兄弟节点索引查询，用于园丁、凯撒蟹及 UNRELENTING 等真实轨迹的审核。`HOTSEARCH_ORACLE_DIR` 可以把审核可执行文件及其依赖保存在独立目录。自然结果全部保留，只有通过严格实际边界和整条原生重放的轨迹进入经过审核的数据文件。模型、宿主、策略实现、预算和裕量共同标识生产策略。研究复现和审核边界见 [1H4 报告](../../docs/m1-infra1h4-search-quality-and-semantics.md)。

## 基础构建和 1H3-R 模式

从独立研究检出的仓库根目录执行下列命令。每次运行使用新的输出目录。

```powershell
python -B engine/HotSearch/build.py
python -B engine/HotSearch/hot_produce.py logs/my-hot-natural --ids 87 176 --limit 32
python -B engine/HotSearch/hot_produce.py logs/my-hot-panel --limit 32
python -B engine/HotSearch/condition.py logs/my-hot-pairs --hot-pairs
python -B engine/HotSearch/condition.py logs/my-hot-worlds --split train
python -B engine/HotSearch/condition.py logs/my-hot-123 --ids 123 --audit
```

自备战斗使用 `hot_produce.py OUTPUT --specs FILE`。FILE 为 UTF-8 JSON 数组，每项含 `family` 和完整原生 synthetic combat `spec`。生产器把这些记录标记为 `custom`。内置自然面板固定为 96 个训练根。每次收到失败回复，当前战斗停止，下一根重新初始化。若原生开局被拒绝，下一个开局使用新的独立宿主；账本累计已退出宿主的 CPU 并保留各次峰值的最大值。独立经验文件为 `natural.jsonl.gz`，资源账本为 `ledger.json`。

构建需要已有研究资产。游戏使用仓库 `lib/sts2.dll`，HotKernel 1.0.2 源码使用同工作区 `hk0-isolated-131d10a/upstream.zip`。构建验证归档和游戏身份，重新应用 HotDraw 观测点并编译到 `logs/hotsearch/rules`。原生开局复用已校验的四份 `infra1h-5d-base2/host/Headless` 源码。既有 `infra1h-hot-k2`、离线 NuGet feed、GodotSharp、RitsuLib 以及 `logs/m0-v5/dotnet9` 提供配套依赖。冻结 G2 位于 `logs/inf1/jobs/dc2b-night1-hf1/g2-fit/best.pt`，V2 位于 `experiments/m1-core5a/evidence/v2.pt`。两个权重加载前均校验 SHA-256。独立可执行文件名沿用上游 friend assembly 名称 `OfflineSearchHarness.dll`。

## 状态和策略

- `Battle.cs` 持有真实状态、冷数据、随机流、公开牌袋和待选重放前缀。开局校验构筑多重集。公开抽牌、洗牌、顶底插入、生成、自动打出和待选更新这一战斗的记录。
- `TurnSearch.cs` 从可见区域、已声明的未知牌类型、公开历史和已宣告敌方行动建立新根。未知牌按公开描述排序并重新绑定实例编号。假设动作复制紧凑状态并共享只读冷数据。HotDraw 在随机点分支；未建模 RNG、预算耗尽、深度及容量限制保留各自的概率质量。
- `kernel/Events.cs` 在随机生成牌进入可交换牌袋时维持成员资格。加权敌方转移按实际浮点扣减规则积分，保留零权重端点在有限随机数网格上的行为。
- `--arm turn` 比较完整 G2 回合参考和候选回合策略。候选首动作取 G2 前两名及结束回合，后续动作按当前公开伤害、格挡和目标生命排序。只有候选与参考都闭合、且候选的冻结 V2 期望更高时才执行替代策略。每个实际回合最多发起一次比较。`--arm feedback` 用 G2 随后续公开观察重新决策，`--arm g2` 直接运行 G2。G2 模型输入与旧部署的预览、待选历史及特征数值仍有差异。
- `Observation.cs` 在战斗内核调用下一回合初始抽牌之前采集 C。记录含真实资源、各公开牌区、合法牌袋约束、敌方行动、能力、费用层和可见历史。胜负终局记录战斗资源。独立原生审核在领取房间奖励之前读取金币。
- `Worlds.cs` 在稳定 B 保存快照，恢复时重建可变元数据。配对自然后缀使用同一原世界。条件世界只重排可交换尾部；两个策略共享同一世界和真实未来随机流。审计另行扰动随机流，校验公开搜索结果后恢复实验世界。
- `condition.py` 的 `--hot-pairs` 使用本引擎自己的自然前缀。5E 桥接面板只读取冻结历史动作，所有前缀和后缀都在 HotKernel 上执行。当前根选择固定在第 2 回合，候选包含“首动作后结束回合”及继续战术出牌两类。每个被选程序均保留独立条件分布、C 特征键和完整公开 C 键。

## 证据与复现

```powershell
python -B engine/HotSearch/build_oracle.py
python -B engine/HotSearch/frozen_audit.py logs/my-frozen-replay
python -B engine/HotSearch/native_audit.py logs/my-native logs/my-hot-panel/natural.jsonl.gz
python -B engine/HotSearch/verify.py
```

`--diagnostic` 显式开启失配后的影子采集，以便测量新策略的整战能力；每次失配仍保留原分布和实际边界。打包数据中的 `strict` 为停止模式，`natural` 为诊断模式，`natural-reviewed` 为停止模式完成且通过整战原生重放的交集。条件世界默认同时检查干预回合的完整公开边界和后续回合全部已闭合的预测。发生失配即停止这一侧；同根的双方及全部预定世界通过后，该根才进入严格统计。`strict-train`、`strict-dev`、`strict123`、`strict-pairs` 为此模式。`world-train`、`world-dev`、`123`、`pairs` 记录仅审核首个干预边界、继续采集后续诊断轨迹的对照。不同策略、训练和开发世界分别存储。正式运行可用 `campaign.py LABEL SCRIPT ARGS...` 共用一个串行 worker 账本。命令、验收数字和缺口见仓库的 [1H3-R 研究报告](../../docs/m1-infra1h3r-independent-hot-search.md)。
