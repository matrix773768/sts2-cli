# M1-S3A 修复版生产接入与困难根试生产

**修复版已通过 B1B 常驻接入。** 新旧 Solver 各在一个进程内完成七个开发位置，包含跨角色、遭遇和幕数的 A→B→A。困难批次 24/24 均完成原生建根和预测记录落盘，F3B 找到 3 条完整预测胜路。其余 21 根全部保留搜索证据，并通过丢弃宿主继续生产。

基线 `757dcf8`，分支 `port/v0.113.1`。Windows、SDK 10.0.404、CoreCLR 9.0.7、STS2 v0.113.1／Build 26660232。未读取旧验证或封存测试根。预测记录使用 `prediction_only`、`synthetic=true`、`natural_reachability=unknown`。未改变历史预测与 L3 标签。

## Solver 接入与一致性

新版 B1B `produce` 默认使用冻结 0.51.5，也可显式选择 `0.51.5-e3f.1`。历史生产入口仍可用 `--legacy`。修复版要求构建清单与独立 E3F 资格证据对应，核对原生和补丁身份及目标 DLL 的磁盘 SHA-256。每次启动后再次在宿主内读取实际加载的程序集版本和 SHA-256，验证通过才处理根。版本、哈希和运行时证明逐条写入记录。

| 版本 | 本轮验证的 Solver SHA-256 |
| --- | --- |
| 0.51.5 | `d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13` |
| 0.51.5-e3f.1 | `cea50e9570edbed06c7f0502fdc5949ba3846ee64605f4891b32768b4ef3d51c` |

修复版经过 E3F 两个原生终局与多主要敌人专项后，生产记录只取消 `E3_PREDATOR_TERMINAL` 和 `E3_PREDATOR_FIRST_WIN`。冻结版照常保留。原生退役的其它 stamp 差分仍按原机制记录和隔离，敌方侧 `Y`／`AttackStarts` 不享有豁免。新旧七个位置的根身份、终选动作、HP、以及原生退役帧哈希一致。同版本 A 重复的语义摘要一致。冻结版两个猎杀者首胜的退役差分分别在第 16、7 步，修复版两处均消失。[冻结配对](../experiments/m1-s3a/frozen-pair.json.gz) · [修复版配对](../experiments/m1-s3a/fixed-pair.json.gz)

## 生成能力与计划

用原生 ModelDb 只读枚举普通／精英／Boss。第二幕 HIVE 有 14／3／3 个，第三幕 GLORY 有 12／3／3 个。第一幕有 OVERGROWTH 与 UNDERDOCKS。现有 S2A 建根验证明确限制第一、二幕，遭遇须为相应幕变体的普通成员，二者也是 B1B 准入边界。目录出现的第三幕、精英和 Boss 仅证明有注册模型，当前人工建根和安全退役均缺乏资格证据。后续须独立验证第三幕挂载、敌方起始 hook、Boss 或精英奖励以及退役边界。试生产未放开这些约束。[原生目录](../experiments/m1-s3a/catalog.json.gz)

[冻结计划](../experiments/m1-s3a/plan.json) 用新种子域 `STS2-S3A-V1` 和固定生成器种子 533017。按角色、6 个构筑模板、遭遇、入场压力和人工生成来源分层，规划 **144 根**。4 个开发遭遇（96 根），单独的验证及测试遭遇各 24 根。幕暂锁定第二幕，角色各半。四个重复索引的配方固定为每个独立的遭遇／模板组合派生种子，12–15 张牌、0–2 张升级、难度 A0 或 A2，HP 分为 6–14、15–27、36–52 三档。后续计划含最大 144 个不同输入，本次只生成开发索引 0。真实来源及自然可达性证据另建层，本轮没有真实跑局来源，原生可构造不赋予自然可达标签。

试产 24 个输入覆盖 `BOWLBUGS_NORMAL`、`EXOSKELETONS_NORMAL`、`MYTES_NORMAL` 和 `CHOMPERS_NORMAL`。模板为成长、力量、火焰屏障防御、循环、毒和开场爆发，两个角色各 12 根。紧缺档禁初始遗物与药水，资源对照档保留起始遗物与 Flex Potion，搜索均禁主动用药。24 根都原生合法建根，6 根在第二档独立重建时根摘要一致。验证和测试配方仅登记，未生成输入或运行。[冻结试产输入](../experiments/m1-s3a/pilot.json)

## 失败、恢复与实测

每个位置先跑 F3B C。512 主批中预先选择六个跨模板位置允许 F4，仅其中一个首胜成功并完成剩余 468 次转移的固定优化，保留 3 HP 终选。所有失败都写出状态、完整分支诊断和转移。无可用胜路时宿主退出，下一根冷启动。只用已经找到的首胜合法退役，继续沿用 B1B 的地图清理和 profile 核对。schema 2 日志受输入与版本合同保护，逐位置原子落盘。恢复只继续已有连续位置之后，匹配实际 Solver 与宿主哈希，输入、版本或预算合同变化时拒绝混入。实测用两条记录停下，再恢复一条，前两条的文件哈希保持一致，计数 2 旧、1 新。[恢复证据](../experiments/m1-s3a/resume-proof.json)

| 512 困难主批 | 数量 |
| --- | ---: |
| 有效原生建根／全部位置 | 24／24 |
| 首胜 | 3／24 |
| 候选耗尽／转移上限 | 16／5 |
| 根级超时／unsupported | 0／0 |
| 无安全退役路线而丢弃 | 21 |
| 冷启动／继续常驻 | 22／2 |

分支层另有 1,718 条死亡、37 条 unsupported、3 条胜路及 1 条截断。分支 unsupported 及细节原样存档，根级候选耗尽包含这些分支。三个胜路终选为 24、3、3 HP。低 HP 两档均未找到胜路，资源对照档 3/8 成功。另对预定六根从独立进程批次以 128 次上限实跑，只跑 F3B。两档同为 1/6 首胜，成功根均用 40 次转移，另外四根在 128 档达到上限、512 档候选耗尽。预算结果来自独立执行。[512 逐根](../experiments/m1-s3a/hard.json.gz) · [128 独立重跑](../experiments/m1-s3a/budget128.json.gz)

| 分组 | n | 每根墙钟 P50／P90 ms | F3B 热搜索 P50／P90 ms |
| --- | ---: | ---: | ---: |
| B1B 修复版简单热对照，含 F4 和退役 | 3 | 354／365 | 见逐根 |
| B1B 修复版复杂热对照，含 F4 和退役 | 3 | 854／873 | 见逐根 |
| 困难 512，最低 HP | 8 | 3,332／3,675 | 673／851 |
| 困难 512，紧缺 | 8 | 3,594／3,739 | 671／887 |
| 困难 512，资源对照 | 8 | 3,903／4,352 | 812／946 |

困难主批 83.76 秒，含落盘与退出，吞吐 **0.287 条全状态记录/秒**，其中完整预测胜路 **0.036 条/秒**。22 个冷位置的启动与验证中位数 318 ms，原生初始化中位数 1,660 ms。除首次外，21 次额外冷启动的握手与身份校验累计 6.88 秒，独占模型初始化累计 26.47 秒，合计 33.36 秒。这两个数是已测区间的加总，未估算健壮热替代方案的反事实差额。难例进程最高工作集约 136 MiB。简单热对照只有三条，困难分组各八条，P90 用于描述该批次。[结构化汇总](../experiments/m1-s3a/summary.json)

按同种困难混合、同样的单 worker 和 F4 覆盖线性外推，100／1,000 个输入约需 **5.8／58 分钟**。逐根 JSON 约 32／318 MB，引擎日志另约 82／815 MB。内存为单 worker 已测进程工作集，加上控制器及系统开销。失败比例、额外 F4、日志保留 policy 和并发会改变需求。该估计不外推胜率。对这批困难根，优先进一步研究 F3B 首胜覆盖和失效后摊销成本，扩大 F4 标注等有稳定首胜数据后进行。

## 复现与检查

在仓库根，用本地冻结 Solver、E3F 修复构建、本地游戏和 RitsuLib。已登记的修复哈希可用原 E3F Release 目录。若重建导致哈希变化，先重跑 E3F 独立专项，并用 `--qualification` 指向新结果，再使用对应构建。恢复时须使用相同合同。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
python -X utf8 experiments/m1-s3a/build_host.py
python -X utf8 experiments/m1-s3a/produce.py catalog logs/m1-s3a/catalog-repro
python -X utf8 experiments/m1-s3a/generate.py logs/m1-s3a/catalog-repro/catalog.json logs/m1-s3a/pilot-input-repro.json
python -X utf8 experiments/m1-b1b/run_probe.py produce logs/m1-s3a/frozen-repro --input experiments/m1-s3a/version-pair.json --solver 0.51.5
python -X utf8 experiments/m1-b1b/run_probe.py produce logs/m1-s3a/fixed-repro --input experiments/m1-s3a/version-pair.json --solver 0.51.5-e3f.1 --solver-build logs/m1-e3f/release
python -X utf8 experiments/m1-b1b/run_probe.py produce logs/m1-s3a/hard-repro --input experiments/m1-s3a/pilot.json --solver 0.51.5-e3f.1 --solver-build logs/m1-e3f/release
python -X utf8 experiments/m1-b1b/run_probe.py produce logs/m1-s3a/budget-repro --input experiments/m1-s3a/budget-128.json --solver 0.51.5-e3f.1 --solver-build logs/m1-e3f/release --cap 128 --first-only
python -X utf8 experiments/m1-s3a/summarize.py logs/m1-s3a/summary-repro.json logs/m1-s3a/hard-repro/results.json logs/m1-s3a/budget-repro/results.json
python -X utf8 -m pytest experiments/m1-s3a/test_hard_pilot.py experiments/m1-b1b/test_resident_production.py experiments/m1-e3f/test_predator_fix.py -q
```

使用同一输出依次指定 `--max-new 2` 与 `--max-new 1` 可复现恢复。隔离构建、实机版本配对、24 条困难主批与 6 条独立预算记录、9 项定向测试通过。未运行全量 pytest 或五角色批次。
