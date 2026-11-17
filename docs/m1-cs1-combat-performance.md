# M1-CS1 CombatSolver 性能基准与首轮优化

2026-11-17。大牌组场景将单线程预热搜索分配从约 515 MB 降到 303–304 MB（−41%），保持 300 次展开、1,823 次转移及完整动作序列。保留隔离候选补丁。该场景候选耗时两次相差 2.59 秒，速度收益需要更多独立样本确认。

## 版本与复现

CombatSolver 0.51.5，官方 main `78e4545e825e58c3d999354b1ffcd54241b1d2cf`。Git 克隆遇到 Schannel 不受信任根证书错误，采用 M1-P0 保存的同提交官方 ZIP，SHA-256 `4e2fc327db65f1ea105026476083e72645dfe9189d722c6175115a19408d55cf`。实验根为与 sts2-cli 同级的 `CombatSolver-m1-cs1/`。[上游提交](https://github.com/Torch1230/CombatSolver/commit/78e4545e825e58c3d999354b1ffcd54241b1d2cf)

Windows x64，16 个逻辑处理器，Steam v0.113.1 Build 26660232，Harmony 2.4.2，RitsuLib 0.6.14（API 目标 0.113.0）。SDK 10.0.404，运行固定 CoreCLR 9.0.7，依赖 Godot.NET.Sdk 4.5.1 和 Krafs.Publicizer 2.3.0。三个夹具均可建根和搜索，验证范围为离线宿主。构建使用 `CopyModOnBuild=false`。Windows MemoryCleaner 的 net48 包还原遇到 TLS EOF，离线构建显式指定 Windows 游戏数据目录并用 `OS=OfflineExperiment` 跳过该独立工具的构建。

在工作区父目录运行。下面的脚本及两个补丁保存在上述实验根。冷测时确保 DLL 环境变量未设，且工作目录中的 solver 构建为基线。热测使用冻结的 `baseline.dll` 和 `candidate.dll`，由宿主环境变量切换。复跑时使用新结果目录或调整脚本输出名。

```powershell
$exp = (Resolve-Path CombatSolver-m1-cs1).Path
$src = Join-Path $exp 'CombatSolver-78e4545e825e58c3d999354b1ffcd54241b1d2cf'
$steam = "$env:USERPROFILE/Desktop/STEAM"
$data = "$steam/steamapps/common/Slay the Spire 2/data_sts2_windows_x86_64"
$env:DOTNET_CLI_HOME = (Resolve-Path sts2-cli/logs/dotnet-home).Path
$env:NUGET_PACKAGES = (Resolve-Path sts2-cli/logs/nuget-packages).Path
dotnet build "$src/CombatSolver.csproj" -c Release -p:OS=OfflineExperiment -p:CopyModOnBuild=false "-p:SteamRoot=$steam" "-p:Sts2DataDir=$data" -p:NuGetAudit=false
Copy-Item "$src/.godot/mono/temp/bin/Release/CombatSolver.dll" "$exp/baseline.dll"
dotnet build "$src/tools/search/OfflineSearchHarness/OfflineSearchHarness.csproj" -c Release "-p:SteamRoot=$steam" "-p:CombatSolverRepositoryRoot=$src" -p:NuGetAudit=false
& "$exp/run-cold.ps1"
# 在干净快照上分别应用以下补丁，然后各重建相应项目。
git -C $src apply "$exp/shuffle-order.patch"
git -C $src apply "$exp/harness-probes.patch"
# 将重建后的求解器 DLL 复制为 $exp/candidate.dll。
& "$exp/run-abba.ps1"
$env:M1CS1_COMPARE_TOOL = "$src/tools/search/OfflineSearchHarness/compare_results.py"
python -X utf8 "$exp/compare-m1cs1.py" $exp
```

冷测各启一个新进程，Evaluate、Custom、Beam 24、分支上限 32/18/24、Smart、常规 GC，节点额度 1,000、软期限 20 s。用固定种子 `M1CS1`、IRONCLAD、`FUZZY_WURM_CRAWLER_WEAK` 做普通战；`prepare-veryhigh.py` 生成 `pressure-queen`（45 牌、13 遗物、双敌人）和 `silent-large-deck`（开局活跃牌堆 396 张、AEONGLASS_BOSS）的请求。仅执行这些输入。热测降至 300 节点、30 s 软期限、DOP 1。每次启动一个进程，同根先热身一次再测一次，按基线→候选→候选→基线。各对照都没有触发时间边界。

## 冷进程基线

表中秒数为首次搜索请求墙钟，包含根捕获和首次搜索路径 JIT。启动后至首个玩家回合另计，小战 DOP 1 的建根前置阶段合计约 4.42 秒。分配取阶段诊断合计，RSS 为全进程高水位；MB 为十进制。

| 夹具 | DOP | 秒 | 展开 / 转移 | 展开/s | 分配 MB / RSS MiB | GC 0/1/2，暂停 ms | 预测失血 / 用药 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 小战 | 1 | 2.624 | 153 / 423 | 58 | 18.5 / 164.5 | 2/0/0，12 | 0 / 0，完整路线 |
| 小战 | 4 | 1.932 | 153 / 423 | 79 | 18.7 / 161.9 | 2/0/0，19 | 0 / 0，完整路线 |
| Queen | 1 | 18.078 | 1,000 / 8,673 | 55 | 547.7 / 251.7 | 63/29/4，1,310 | 20 / 3，节点边界 |
| Queen | 4 | 11.273 | 1,000 / 8,673 | 89 | 565.2 / 221.6 | 66/28/5，1,288 | 20 / 3，节点边界 |
| 大牌组 | 1 | 15.077 | 1,000 / 5,540 | 66 | 1,524.1 / 282.2 | 170/49/7，923 | 16 / 0，节点边界 |
| 大牌组 | 4 | 14.294 | 1,000 / 5,772 | 70 | 1,598.6 / 285.5 | 188/56/9，1,719 | 16 / 0，节点边界 |

Queen 的同工作量 DOP 4 墙钟约缩短 38%。大牌组的两档实际转移不同，且两档都只有一次样本。

### 隔离微测

给已应用探针补丁的宿主设置 `M1CS1_MICRO=1`、`M1CS1_FORK=1` 和 `OFFLINE_HARNESS_COMBATSOLVER_DLL=<baseline.dll>`，沿用上述输入并加 `--milestone M1 --dop 1`。Fork 预热 256 次、测 4,096 次，键、快照及动作各预热 32 次、测 512 次。下表为单批均值 µs / B。

| 夹具 | 根模拟器 Fork | 状态键 | 完整快照评价（含键） | 有效 Strike 转移 |
| --- | ---: | ---: | ---: | ---: |
| 小战 | 29.5 / 5,736 | 30.4 / 584 | 217 / 4,345 | 243 / 11,364 |
| Queen | 163 / 10,112 | 82.4 / 1,240 | 739 / 8,688 | 未测 |
| 大牌组 | 259 / 35,160 | 73.6 / 616 | 3,368 / 181,320 | 未测 |

键和评价反复读同一根，卡牌指纹为热缓存。动作使用预先 Fork 的独立子状态，计入寻找卡、合法性检查和 `ManualPlay`，每个子状态核对敌方掉 6 HP。该探针覆盖非击杀、无选牌的打击，后续死亡结算和跨回合是不同操作。

## 热点与优化

- **大牌组**的首要成本是投影洗牌，单线程冷测阶段为 6.94 s / 991 MB，约占阶段分配 65%。Fork 次之（0.76 s / 216 MB），其后按分配为卡牌执行（1.03 s / 78 MB）。快照剩余阶段约 1.32 s，保留约 0.35 s。
- **Queen** 的阶段墙钟主要是卡牌执行 2.48 s、快照 2.29 s、投影洗牌 1.75 s、Fork 1.42 s、保留 1.00 s。Fork 分配居首（133 MB），其次为卡牌执行（80 MB）和投影洗牌（48 MB）。战斗指纹阶段 0.66 s / 8.6 MB。常规 GC 暂停可观。
- **小战**单独的 Fork 和排序开销较小，首轮 JIT、卡牌执行、收尾及保留的占比更大。阶段计时是排他归属的墙钟量，DOP 4 的 worker 阶段时间可以重叠。候选生成、Hook、转置表及调度没有各自独立的 CPU 比重；保留阶段包含多项操作。大牌组并行的额外转移和 GC 暂停提示按固定 DOP 比较候选。
- Queen 的 `dotnet-trace` 9.0.661903 用 `collect --providers Microsoft-DotNETCore-SampleProfiler --output queen.nettrace -- <dotnet> --fx-version 9.0.7 <harness> ...` 采整进程，含启动与两次搜索。TopN 的独占采样被 JIT（27.31%）及线程等待占主导，可见 MemberwiseClone、集合拷贝和 Snapshot。采样是全进程线程栈分布，搜索热点排序主要依赖阶段数据与隔离探针。

此前已有原地投影洗牌、牌组缓冲复用、转置表内联单标签。未重复储君无显著加速的 Fork 监听缓存或已撤回的选择就绪负缓存。本轮仅在 `CombatCardOrdering.Compare` 的动态变量最后一层比较中，对 0/1 个键直接遍历，多个键仍使用原 Ordinal 顺序，保留逐键比较、平局、排序调用和 RNG 消费。共享比较器也用于实际预测洗牌。

| 热样本 | 展开 / 转移 | 分配 MB，基线 → 候选 | 秒，基线 → 候选 | 峰值 RSS MiB，基线 → 候选 | 预测失血 / 用药 |
| --- | ---: | --- | --- | --- | --- |
| 小战 | 153 / 423 | 16.44、16.52 → 15.59、15.54 | 0.618、0.589 → 0.504、0.575 | 169.5、169.9 → 169.7、165.7 | 0 / 0，回合 3 完整路线 |
| Queen | 300 / 2,646 | 162.16、163.87 → 155.62、154.75 | 3.751、4.300 → 4.129、3.779 | 230.2、221.0 → 218.8、215.5 | 8 / 2，节点边界 |
| 大牌组 | 300 / 1,823 | 515.57、514.70 → 302.94、304.03 | 4.545、4.392 → 4.358、1.766 | 240.9、246.2 → 245.6、237.7 | 38 / 0，节点边界 |

热测使用进程分配差值，RSS 含预热。三个场景的总分配均值降约 5.6%、4.8%、41.1%。大牌组投影洗牌阶段从约 329 MB 降至 118 MB，几乎解释该场全部分配降幅。大牌组 Gen0 从 59/59 次降至 36/36，Gen1 从 17/18 降至 16/16，Gen2 均为 4，暂停从 492/508 ms 降至 440/197 ms。Queen 暂停为 323/349 → 316/302 ms，小战为 26/28 → 30/18 ms。进程峰值未显示与累计分配成比例的变化。每版每根两次，仅报告观测范围，不估计尾延迟。

## 正确性、范围及下一步

六对样本复用上游 `compare_results.py` 的比较函数，逐字段共比 534 项，另核对完整 PlanActions，均一致。对照包括根与夹具指纹、非耗时/内存的搜索指标、路线及已有续用戳。ABBA 跑了现有洗牌 witness，检查原生比较符号、排序结果和 live 根隔离。候选 Queen 另跑 100 节点 `--verify-incremental`，完成 1,023 次转移的增量与完整预测回放核对。没有执行原生完整路线部署、全量 pytest 或五角色整局。预测节点边界的失血读数仅用于同配置质量对照。

原始 JSON、比较报告、洗牌 witness 及 trace 保存在实验根。基线 DLL SHA-256 为 `d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13`，候选为 `8924ee8f68c84f9b0d14c3560ac411ff6cdcf253d818e3eeb0f9113f5654dabb`。用 `git apply -R shuffle-order.patch` 可撤回候选源码。主项目仅提交本报告。

下一项优先对 Queen 作 Fork 内部分配栈切分，测量各分支对象及首次写入，寻找能在保持 COW 隔离及共享根语义的情况下省掉的容器复制。另在隔离原生宿主用一条经过洗牌的固定路线对账牌序、RNG 与终态，作为纳入正式数据生成前的验证。

按大牌组样本等工作量计算，每万次搜索累计少分配约 2.12 TB，意义主要在 GC 压力和多 worker 可持续性。实际样本吞吐还取决于牌组分布、原生回放、样本写入和并发内存上限。小战和 Queen 的分配降幅更小，当前数据不足以承诺端到端训练样本/秒提升。
