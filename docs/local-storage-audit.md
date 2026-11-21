# STS2 CLI 本地存储审计

2026-11-21（中国标准时间）。分支 `port/v0.113.1`，HEAD `61a004c6059ac888596579033e767dcebec9342d` 与本地远端跟踪引用一致。统计仓库 `sts2-cli`，同级 Solver 源码树仅纳入依赖分析。扫描按普通文件逻辑长度计量，跳过 Windows 重解析点。修改时间取目录内最新文件时间。GB 为十进制，MiB 为二进制。扫描为实时观察，清理前须复测。

## 结论与空间

同一字节数换算为二进制单位，仓库约 6.72 GiB，`logs/` 约 6.57 GiB。II-H.2 现有 Solver DLL 的实测 SHA-256 与 build.json 一致。审计未运行构建、原生验证或训练。

仓库 **7.214 GB**，其中 `logs/` **7.052 GB**，占 97.8%，94462 个文件。顶层按目录汇总，另列日志根直属文件。日志目录实地枚举 395 个，附录列出含普通文件的汇总和静态引用。Git 索引没有 logs 路径，`.gitignore:14` 忽略 logs。未逐项证明 P3 资格，截至本次审计可直接删除的已确认容量为 **0 GB**。

| 方案 | 拟审查范围 | 项目内可释放上限 | 外部压缩归档估计 |
| --- | --- | ---: | ---: |
| 最保守 | test-engine 中确认停写、无当前依赖的历史会话 | 0.639 GB | 最高约 0.447 GB |
| 适度 | 上项及正式训练、性能矩阵和历史诊断的 P2 候选（`m1-n2c-formal`、`nosl3c-formal-v2`、`nosl3c-ib-final-workers`、`nosl3c-ib-final-large`、`m1-f6a`、`m1-s3b`、`nosl3c-formal`、`nosl3c-ib-final-matrix`、`nosl3b-formal`） | 2.126 GB | 最高约 1.488 GB |
| 激进 | 上述候选再加 `m1-n2b-formal`、`m1-n2a2-cohort`、`m1-ls1-run`、`m1-b1b`、`m1-s3a`、`m1-n2f-a` | 2.530 GB | 最高约 1.771 GB |

以上是候选池上限，须扣除活动会话、仍被消费的路径、唯一原始证据、唯一模型检查点和冻结输入。未确认可归档的容量下限为 0。外部空间按假设压缩后为原大小的 30–70% 规划，表中取区间上端，未实际试压；已压缩、加密文件或包含副本的集合可能接近原大小。实际操作先预留原大小用于归档，再预留一份原大小用于解包核验。同卷归档的净释放量为获准删除的源字节减去归档字节，同卷直接搬移的净释放为 0。首批只挑 `test-engine` 中可对应到已结束、无待查故障且无消费者的旧 pytest 会话；目前缺逐会话通过/失败清单，不能仅按日期或 failure.txt 是否存在推断成功。观察时未列出匹配的游戏、dotnet 或 Python 进程，这一时点观察不证明后续无写入。

## 最大 30 个目录

| 目录 | MiB | 文件数 | 最新（MM-DD hh:mm） | 分类 | 依赖及可恢复性 | 建议 |
| --- | ---: | ---: | --- | --- | --- | --- |
| `logs/m1-review-dotnet` | 726.03 | 5328 | 11-17 12:57 | P1 | 脚本直引或关键历史输入 | 保留，先验证替代链 |
| `logs/test-engine` | 609.32 | 8162 | 11-21 10:31 | P2 / P0 | pytest 活动输出根；历史会话含宿主诊断 | 逐会话归档，保留活动及超时证据 |
| `logs/nuget-packages` | 273.99 | 1302 | 11-17 19:48 | P1 | 脚本直引或关键历史输入 | 保留，先验证替代链 |
| `logs/m1-e3f` | 255.57 | 3791 | 11-19 13:39 | P4 | 历史探针与多份 Solver 构建混存 | 分离证据与构建后逐项核对 |
| `logs/m1-n2c-formal` | 227.46 | 772 | 11-19 17:17 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/nosl3c-formal-v2` | 171.20 | 1215 | 11-20 12:15 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/nosl3c-ib-final-workers` | 170.94 | 1853 | 11-20 13:12 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/nosl3c-ib-final-large` | 164.86 | 1646 | 11-20 13:26 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/m1-f6a` | 162.90 | 66 | 11-19 13:24 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/m1-s3b` | 157.31 | 498 | 11-19 14:07 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/nosl3c-formal` | 138.38 | 1202 | 11-20 12:05 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/nosl3c-ib-final-matrix` | 113.89 | 1181 | 11-20 13:06 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/nosl3b-formal` | 110.86 | 368 | 11-20 11:32 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/ls2a-production` | 85.86 | 4172 | 11-19 20:54 | P1 | 脚本直引或关键历史输入 | 保留，先验证替代链 |
| `logs/m0-v5` | 76.10 | 202 | 11-17 13:05 | P0 | 当前认证、冻结输入或原生环境 | 原位保留 |
| `logs/m1-n2b-formal` | 72.30 | 388 | 11-19 16:44 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/m1-n2a2-cohort` | 66.19 | 385 | 11-19 16:19 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/m1-p0` | 65.99 | 2433 | 11-20 21:45 | P4 | 用途或精确恢复链未闭合 | 保持原位 |
| `.git` | 65.74 | 1604 | 11-21 10:46 | P0 | Git 对象与工作树基础 | 保护 |
| `logs/m1-ls1-run` | 65.14 | 595 | 11-19 19:58 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/m1-b1b` | 64.67 | 163 | 11-19 13:10 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `experiments` | 60.03 | 911 | 11-21 10:36 | P0 | 源码、实验合同与提交证据 | 保护 |
| `logs/m1-s3a` | 59.16 | 200 | 11-19 13:54 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/m1-n2f-a` | 58.16 | 1285 | 11-19 19:04 | P2 | 历史完整账本、性能诊断或训练输出；复现与读取路径待核定 | 整树无损外部归档，原位保护唯一输入 |
| `logs/m1-nosl3c-iih2-candidate` | 57.00 | 900 | 11-20 23:45 | P0 | 当前认证、冻结输入或原生环境 | 原位保留 |
| `logs/m1-nosl3c-iih-candidate` | 57.00 | 900 | 11-20 23:23 | P4 | 用途或精确恢复链未闭合 | 保持原位 |
| `logs/m1-nosl3c-iig-completion-candidate` | 56.99 | 900 | 11-20 21:37 | P1 | 脚本直引或关键历史输入 | 保留，先验证替代链 |
| `logs/m1-nosl3c-iig-completion-recovery` | 56.98 | 900 | 11-20 21:31 | P4 | 用途或精确恢复链未闭合 | 保持原位 |
| `logs/m1-nosl3c-iig-completion-draw` | 56.97 | 900 | 11-20 21:25 | P4 | 用途或精确恢复链未闭合 | 保持原位 |
| `logs/m1-nosl3c-iig-completion-diag2` | 56.96 | 900 | 11-20 21:21 | P4 | 用途或精确恢复链未闭合 | 保持原位 |

## 最大 20 个文件

| 路径 | MiB |
| --- | ---: |
| `logs/m1-n2c-formal/ledger.json` | 83.77 |
| `logs/m1-n2a2-cohort/results.json` | 47.75 |
| `logs/m1-review-dotnet/sdk/10.0.404/FSharp/FSharp.Compiler.Service.dll` | 39.98 |
| `logs/m1-s3b/diagnostic/results.json` | 39.45 |
| `logs/m1-n2d-formal/ledger.json` | 33.71 |
| `logs/nosl3b-formal/training.sqlite` | 29.94 |
| `logs/nosl3c-formal-v2/training.sqlite` | 26.71 |
| `logs/m1-n2f-a/ledger.jsonl` | 25.23 |
| `logs/m1-s3b/development/results.json` | 23.42 |
| `logs/m1-f6a/paired-final/results.json` | 22.20 |
| `logs/m1-f6a/paired/results.json` | 22.20 |
| `logs/m1-b1b/sequence/results.json` | 21.26 |
| `logs/nuget-packages/microsoft.netframework.referenceassemblies.net48/1.0.3/microsoft.netframework.referenceassemblies.net48.1.0.3.nupkg` | 20.03 |
| `.git/objects/pack/pack-5212a4b034adb403684a70331992f9578e37d18e.pack` | 19.10 |
| `logs/m1-review-dotnet/sdk/10.0.404/Roslyn/bincore/Microsoft.CodeAnalysis.CSharp.dll` | 18.31 |
| `logs/m1-review-dotnet/sdk/10.0.404/Microsoft.CodeAnalysis.CSharp.dll` | 18.31 |
| `logs/m1-n2b-formal/ledger.json` | 15.35 |
| `logs/m1-review-dotnet/shared/Microsoft.NETCore.App/10.0.15/System.Private.CoreLib.dll` | 15.29 |
| `logs/m1-review-dotnet/shared/Microsoft.NETCore.App/9.0.7/System.Private.CoreLib.dll` | 14.56 |
| `logs/m0-v5/dotnet9/shared/Microsoft.NETCore.App/9.0.7/System.Private.CoreLib.dll` | 14.56 |

## 日志文件扩展名分布

| 扩展名 | MiB |
| --- | ---: |
| `.log` | 3220.66 |
| `.dll` | 1412.42 |
| `.json` | 652.74 |
| `.xml` | 376.75 |
| `.jsonl` | 216.25 |
| `.cs` | 203.08 |
| `.sqlite` | 197.80 |
| `.pdb` | 155.94 |
| `.gz` | 65.10 |
| `.nupkg` | 59.27 |
| `.exe` | 38.00 |
| `.py` | 28.90 |
| `.pyc` | 21.79 |
| `.zip` | 17.70 |
| `.pt` | 16.04 |
| `.save` | 11.42 |
| `.gif` | 6.92 |
| `.md` | 6.38 |
| `.lib` | 3.14 |
| `.globalconfig` | 2.53 |
| 其余 53 种 | 12.76 |

## 内容重复

在 logs 内对长度至少 1 MiB 且大小相同的候选按块计算 SHA-256。确认 99 组，按每组只保留一份计算的额外逻辑容量为 0.994 GB。此数包含认证构建等受到保护的路径，与归档方案可能重叠。没有验证 NTFS 实际分配或硬链接，未将重复容量计入收益。小文件未散列，读取失败的文件未列为重复，执行前还需对稳定快照复核。

| 单份 MiB | 副本数 | SHA-256 | 两个示例路径 |
| ---: | ---: | --- | --- |
| 10.05 | 19 | `f36847bd03c1a9d172a56bceb754f51869221baa328c250174864cb642485cbe` | `logs/m1-e3f/final-solver/source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll`、`logs/m1-e3f/fixed/source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` |
| 5.81 | 19 | `3f6b673544929e27d51ce91bc467c427d2a6ade6a9dbd19f77019470ab828291` | `logs/m1-e3f/final-solver/source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.xml`、`logs/m1-e3f/fixed/source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.xml` |
| 5.35 | 19 | `0e4897ecdfb31456a97c7d8028dfb8d7dbdc632e2f73fc9b438d7b266a139289` | `logs/m1-e3f/final-solver/bin/GodotSharp.dll`、`logs/m1-e3f/fixed/bin/GodotSharp.dll` |
| 1.98 | 35 | `9ae71a929bed3de02f5a59420155c9891763c20a1b7794e44ad0eba3a56415e1` | `logs/m1-b1-baseline/logs/test-engine/game-cpey_cmn/stdout.log`、`logs/test-engine/game-04043pai/stdout.log` |
| 1.98 | 35 | `74b104820b5caa788df6fb48580fb7d95d9a255c8983b09cbff3e7234f4742e0` | `logs/m1-b1-baseline/logs/test-engine/game-pm46gfym/stdout.log`、`logs/test-engine/game-0b9i5ws5/stdout.log` |
| 1.03 | 30 | `aee1c3d6d40a1fed7b69e21d5bfe23201cd788b86a2a93ff3562a23fec491f94` | `logs/m1-b1-baseline/logs/test-engine/game-8lu0yeik/stdout.log`、`logs/test-engine/game-0b404kvm/stdout.log` |
| 18.31 | 2 | `6261b74de4ed457e11ca6d0dba1e0b5d81b84d4b34cf95ccaba2b6d4ef7d8742` | `logs/m1-review-dotnet/sdk/10.0.404/Microsoft.CodeAnalysis.CSharp.dll`、`logs/m1-review-dotnet/sdk/10.0.404/Roslyn/bincore/Microsoft.CodeAnalysis.CSharp.dll` |
| 7.30 | 3 | `a6708171773d23000bf45673b97cf0daaa8d34566c6581df6833c3a4a14d411a` | `logs/m1-review-dotnet/packs/Microsoft.AspNetCore.App.Ref/10.0.15/ref/net10.0/System.Runtime.xml`、`logs/m1-review-dotnet/packs/Microsoft.NETCore.App.Ref/10.0.15/ref/net10.0/System.Runtime.xml` |

## 依赖与重建

- **II-H.3／P0**。冻结输入是 `logs/nosl3c-iic-random-final`、`logs/nosl3c-iid-release-independent`、`logs/nosl3c-iie-broad`。保留 `logs/iih3-*`、`logs/iih-e3`、`logs/iih-risk` 和 II-H.2 证据，尤其是训练 SQLite、检查点、RNG、动作历史、失败行和启动超时诊断。提交内的 `experiments/m1-nosl3c-iih3/evidence.json` 是结构化证据，原始账本仍在本机。60 根批次的 38/60 含宿主超时及执行错误，第二次分段更新的等价性仍待验证。复现入口为 [语义收敛报告](m1-nosl3c-solver-semantic-convergence.md)。
- **II-H.2／P0**。H.3 沿用 `logs/m1-nosl3c-iih2-candidate/bin/CombatSolver.dll`，版本 `0.51.5-iih.2`，本机 build.json 登记 SHA-256 为 `d15ba0e66d2bf54dd1d00714c39f7b8ecc26b9a5b35b79ceb64277d4fd4a54dd`。候选重建命令为 `python experiments/m1-nosl3c-iih/build_solver.py logs/audit-rebuild-iih2`。构建链使用本地同级 Solver 源码修订 `78e4545e825e58c3d999354b1ffcd54241b1d2cf`、冻结 baseline.dll、Steam 游戏数据和 Ritsu Workshop 依赖，由 NuGet 和 SDK 提供编译输入。脚本校验 baseline 和游戏 DLL，构建完比较新旧 DLL、build.json 和依赖哈希。单次编译步骤设 150 秒超时，整体预计数分钟，未试跑；原生验证另计。不同目录或工具链可能影响构建哈希，语义认证须保留原二进制或重新验证身份。
- **II-G Completion／P1**。保留 `logs/m1-nosl3c-iig-completion-candidate`、`logs/m1-nosl3c-iig-certified` 和 `logs/nosl3c-iig-completion-*`。旧风险探针显式使用 certified 构建，Completion 同样消费三份冻结账本。候选可用 `python experiments/m1-nosl3c-iig-completion/build_solver.py logs/audit-rebuild-iig` 重建，宿主入口是同目录 `build_host.py`，运行前确认其硬编码输出位置并用独立检出或保留的测试工作区，避免覆盖。原始 16/60 根、逐步诊断和断点续训需要完整回放或训练，优先保留。见 [II-G Completion 复现及回归命令](m1-nosl3c-interaction-completion.md)。
- **原生运行时及构建／P0**。保留 `logs/m0-v5/dotnet9`、`lib`、当前 `src/Sts2Headless/bin/Debug/net9.0` 及其匹配的游戏数据。用 `STS2_DOTNET` 指定该 dotnet.exe，`STS2_DOTNET_VERSION=9.0.7` 固定运行时。游戏 v0.113.1／Build 26660232 的 DLL 哈希见语义收敛报告。SDK 10.0.404 用于构建，CoreCLR 10 不适用于现有 Harmony 路径。旧脚本也直接引用 `logs/m1-review-dotnet` 和 `logs/nuget-packages`。先准备可用的固定 SDK、运行时与离线包镜像，核对版本及包哈希，再用原项目和构建参数在独立位置验证。当前无法从 Git 单独证明可离线恢复 SDK、包和 Workshop 依赖。保留 `logs/dotnet-home` 直至核对 CLI/restore 配置。
- **F4、LS2A、LS2B**。F4 回归读取 `logs/m1-f4/final`，复现默认依赖 `logs/m1-s2a/formal/records.json`。LS2A 的回归可通过 `STS2_LS2A_PILOT` 读取日志根；生产 prepare 依赖独立采样的历史银行。LS2B 的 `logs/ls2b-qualified/search.sqlite` 留有完整 trace，Git 留有公开 gzip 分片、冻结 manifest、模型和实例。保留这些本地输入及生产账本，直至确认替代链。F4/LS2A/LS2B 的已提交摘要和具体回归命令分别见 [F4](m1-f4-route-quality-search.md)、[LS2A](m1-ls2a-scalable-search-experience.md)、[LS2B](m1-ls2b-compositional-strategy-search.md)。
- **旧构建**。例如 `m1-nosl3c-iib-solver-v3` 仍被训练准入文档点名，`m1-e3f-build`、`m1-f6a-build`、`m1-s3b-build` 分别有 `experiments/m1-e3f/build_host.py`、`experiments/m1-f6a/build_probe.py`、`experiments/m1-s3b/build_host.py`。在隔离检出运行对应命令，核对项目、脚本、SDK、游戏和 Solver 哈希。先保护构建树中的 build.json、修改后的源码和失败日志。源码或二进制哈希未匹配前，历史构建仍属 P4。相同 DLL 可能同时服务多个隔离宿主，字节相同不足以证明路径可以移除。
- **测试会话**。`tests/conftest.py` 将每个原生 pytest 会话交给 `python/engine_client.py`，后者独立新建 `game-*`，保存 commands.jsonl、stdout、stderr 和失败诊断。生成入口已确认。历史运行原文及 timeout 证据需要归档，尤其保留含 failure.txt、正在用或被研究引用的会话。测试重跑会生成新会话，成本随选定用例变化，无法恢复历史字节。

## 执行顺序（待单独批准）

1. 用明确的目录白名单记录用途、版本、路径消费者和活跃进程。关闭写入由任务负责人协调，审计不停止任何进程。检查 SQLite 的 `-wal`、`-shm`、`-journal` 及写入句柄，安静时再逐文件取相对路径、长度和 SHA-256。需在线留存时，用 Python 标准库 SQLite 的 `source.backup(destination)` 对每库取一致快照，对快照执行 `PRAGMA integrity_check`；快照与原始证据分别登记，在线快照不作为源目录删除依据。
2. 在新建的、空间充足的外部卷归档目录执行下方命令。逐项检查退出状态，核对解包后的完整路径集合、大小、SHA-256、必要空目录及 SQLite 完整性。对重要证据另保留独立副本。任何差异保留源目录。
3. 恢复测试通过后，提交逐路径删除清单及实测收益供用户另行批准。确认最终绝对路径在仓库的 `logs` 内且无重解析路径。先预览单个获准目录的 `Remove-Item -LiteralPath $approved -Recurse -WhatIf`，再在批准后去掉 `-WhatIf`。避免以整个 `logs` 为目标，保留 Git 对象和索引。
4. 每批检查受影响的构建和最小回归，失败就从已验证的解包副本恢复原路径。II-H.3 的快速门槛是 `python -m pytest -q experiments/m1-nosl3c-iih3/test_certification.py`，涉及宿主时另选一条相关原生用例。涉及 F4、LS2A、LS2B 时按各文档设环境后跑单项，只有改变认证前提时才升级到完整原生验证。

```powershell
# 从仓库根运行。$external 为预先建好且为空的外部卷批次目录。
# $rel 为已核准、已停写且检查过重解析点的单个相对目录，如 logs/test-engine/game-具体名称。
$root = (Get-Location).Path
$restore = Join-Path $external 'restore-check'
$archive = Join-Path $external 'batch.tar.gz'
$manifest = Join-Path $external 'files.csv'
function Get-AuditManifest($base, $relative) {
    Get-ChildItem -LiteralPath (Join-Path $base $relative) -Force -File -Recurse -ErrorAction Stop |
        ForEach-Object {
            [pscustomobject]@{ Path = $_.FullName.Substring($base.Length + 1)
                Bytes = $_.Length
                SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256 -ErrorAction Stop).Hash }
        } | Sort-Object Path
}
Get-AuditManifest $root $rel | Export-Csv -LiteralPath $manifest -NoTypeInformation -NoClobber
tar -czf $archive -C $root $rel
if ($LASTEXITCODE) { throw 'Archive failed' }
Get-FileHash -LiteralPath $archive -Algorithm SHA256
New-Item -ItemType Directory -Path $restore -ErrorAction Stop | Out-Null
tar -xzf $archive -C $restore
if ($LASTEXITCODE) { throw 'Extraction failed' }
$expected = Import-Csv -LiteralPath $manifest
foreach ($base in @($root, $restore)) {
    $actual = Get-AuditManifest $base $rel
    if (Compare-Object $expected $actual -Property Path, Bytes, SHA256) {
        throw 'Manifest mismatch'
    }
}
# 恢复到仓库时，先确认目标路径不存在，再使用 tar -xzf $archive -C $root。
```

## Codex 工作流

- 把工作目录限定为 `sts2-cli`，同级 Solver 树按需单独进入。使用 `git grep -l -e '模式' -- src python tests experiments docs` 或带路径的 `rg -l`，先列命中文件，再读取相关行。避免在父工作区运行 `rg -uuu` 或递归打印整个日志树。
- 没有发现仓库根、docs 或直接父目录中的 AGENTS.md，Git 跟踪列表也没有 AGENTS.md。同级历史 Solver 树有独立指令。PROJECT_STATUS.md 约 53 KB，宜按阶段检索。项目状态和研究文档全部加载会浪费上下文。
- 建议后续新增短版 `docs/CODEX_HANDOFF.md`，记录分支和 HEAD、Solver 版本和哈希、已验证范围、宿主超时及余下修复、证据路径、最小复现命令与数据保护要求。本次只提出建议。
- 测试输出留到独立运行目录，给模型传退出码、计数和失败尾部。优先跑纯逻辑合同和定向原生用例。记录构建身份、运行时、manifest 和测试范围，复用匹配的产物与结论。
- 后续为测试日志写入运行 manifest，记录测试 ID、结果、构建身份、是否需保留和证据索引。短期成功会话设置容量和保留期限，失败、冻结实验及认证证据单独保留。SDK、缓存、构建与证据使用明确的输出根，定期仅生成空间报告和候选清单。

<details>
<summary>日志目录清单、静态引用与最大文件</summary>

引用列仅列 Git 跟踪的脚本、源码或 Markdown 中含字面路径的文件，最多展示两个。未命中仍可能通过参数、分段路径、旧提交、外部脚本或活动任务使用。每个汇总列按占用排序的前三种扩展名。P4 是继续调查项。

| 路径 | MiB | 文件数 | 最新（MM-DD hh:mm） | 分类 | 前三类型（MiB） | 最大文件（相对该组，MiB） | 字面引用 |
| --- | ---: | ---: | --- | --- | --- | --- | --- |
| `logs/m1-review-dotnet` | 726.03 | 5328 | 11-17 12:57 | P1 | .dll 565.34／.xml 124.25／.nupkg 14.57 | `sdk/10.0.404/FSharp/FSharp.Compiler.Service.dll` (39.98) | 10 处文件 · `docs/m1-nosl3a-direct-policy.md`、`docs/m1-nosl3b-learning-efficiency.md` |
| `logs/test-engine` | 609.32 | 8162 | 11-21 10:31 | P2 / P0 | .log 582.09／.jsonl 27.23 | `game-zsh85f_g/timings.jsonl` (2.92) | — |
| `logs/nuget-packages` | 273.99 | 1302 | 11-17 19:48 | P1 | .xml 141.72／.dll 75.46／.nupkg 44.70 | `microsoft.netframework.referenceassemblies.net48/1.0.3/microsoft.netframework.referenceassemblies.net48.1.0.3.nupkg` (20.03) | 16 处文件 · `docs/m1-cs1-combat-performance.md`、`docs/m1-nosl3c-interaction-completion.md` |
| `logs/m1-e3f` | 255.57 | 3791 | 11-19 13:39 | P4 | .dll 137.15／.cs 35.92／.pdb 30.52 | `final-solver/source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | 24 处文件 · `docs/m1-e3f-predator-terminal-fix.md`、`docs/m1-n1-nosl-policy-baseline.md` |
| `logs/m1-n2c-formal` | 227.46 | 772 | 11-19 17:17 | P2 | .log 138.64／.json 84.28／.jsonl 4.53 | `ledger.json` (83.77) | — |
| `logs/nosl3c-formal-v2` | 171.20 | 1215 | 11-20 12:15 | P2 | .log 128.98／.sqlite 26.71／.gz 10.11 | `training.sqlite` (26.71) | 1 处文件 · `docs/m1-nosl3c-training-performance.md` |
| `logs/nosl3c-ib-final-workers` | 170.94 | 1853 | 11-20 13:12 | P2 | .log 140.42／.sqlite 16.16／.gz 6.69 | `w12/training.sqlite` (2.70) | — |
| `logs/nosl3c-ib-final-large` | 164.86 | 1646 | 11-20 13:26 | P2 | .log 138.96／.sqlite 12.72／.gz 6.67 | `large-batched/training.sqlite` (4.25) | — |
| `logs/m1-f6a` | 162.90 | 66 | 11-19 13:24 | P2 | .log 85.24／.json 75.17／.jsonl 2.49 | `paired-final/results.json` (22.20) | 1 处文件 · `docs/m1-f6a-f4-performance.md` |
| `logs/m1-s3b` | 157.31 | 498 | 11-19 14:07 | P2 | .json 85.10／.log 71.99／.jsonl 0.21 | `diagnostic/results.json` (39.45) | 1 处文件 · `docs/m1-s3b-hard-combat-calibration.md` |
| `logs/nosl3c-formal` | 138.38 | 1202 | 11-20 12:05 | P2 | .log 118.93／.sqlite 13.31／.jsonl 4.55 | `training.sqlite` (13.31) | — |
| `logs/nosl3c-ib-final-matrix` | 113.89 | 1181 | 11-20 13:06 | P2 | .log 93.57／.sqlite 10.75／.gz 4.46 | `stock/training.sqlite` (2.69) | — |
| `logs/nosl3b-formal` | 110.86 | 368 | 11-20 11:32 | P2 | .log 64.10／.sqlite 29.94／.gz 7.88 | `training.sqlite` (29.94) | — |
| `logs/(root)` | 91.73 | 401 | 11-21 10:34 | P4 | .jsonl 76.15／.zip 7.36／.log 3.24 | `logs/m1-b1-baseline.zip` (7.36) | — |
| `logs/ls2a-production` | 85.86 | 4172 | 11-19 20:54 | P1 | .log 77.29／.sqlite 4.96／.jsonl 3.47 | `search.sqlite` (4.96) | — |
| `logs/m0-v5` | 76.10 | 202 | 11-17 13:05 | P0 | .dll 74.49／.log 1.25／.exe 0.23 | `dotnet9/shared/Microsoft.NETCore.App/9.0.7/System.Private.CoreLib.dll` (14.56) | 30 处文件 · `docs/m1-b1a-artificial-combat-root.md`、`docs/m1-b1b-resident-prediction-production.md` |
| `logs/m1-n2b-formal` | 72.30 | 388 | 11-19 16:44 | P2 | .log 55.12／.json 15.39／.jsonl 1.79 | `ledger.json` (15.35) | — |
| `logs/m1-n2a2-cohort` | 66.19 | 385 | 11-19 16:19 | P2 | .json 47.75／.log 17.85／.jsonl 0.58 | `results.json` (47.75) | — |
| `logs/m1-p0` | 65.99 | 2433 | 11-20 21:45 | P4 | .json 37.39／.zip 10.34／.cs 9.85 | `source.zip` (10.34) | — |
| `logs/m1-ls1-run` | 65.14 | 595 | 11-19 19:58 | P2 | .log 52.40／.json 9.27／.jsonl 3.46 | `engine/game-ig4jf2pe/stdout.log` (2.21) | — |
| `logs/m1-b1b` | 64.67 | 163 | 11-19 13:10 | P2 | .log 32.92／.json 30.79／.jsonl 0.95 | `sequence/results.json` (21.26) | 1 处文件 · `docs/m1-b1b-resident-prediction-production.md` |
| `logs/m1-s3a` | 59.16 | 200 | 11-19 13:54 | P2 | .json 29.77／.log 29.03／.jsonl 0.36 | `hard/results.json` (8.27) | 1 处文件 · `docs/m1-s3a-hard-combat-pilot.md` |
| `logs/m1-n2f-a` | 58.16 | 1285 | 11-19 19:04 | P2 | .log 31.82／.jsonl 26.34／.md 0.00 | `ledger.jsonl` (25.23) | — |
| `logs/m1-nosl3c-iih2-candidate` | 57.00 | 900 | 11-20 23:45 | P0 | .dll 34.34／.cs 9.01／.pdb 7.64 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/m1-nosl3c-iih-candidate` | 57.00 | 900 | 11-20 23:23 | P4 | .dll 34.33／.cs 9.01／.pdb 7.64 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/m1-nosl3c-iig-completion-candidate` | 56.99 | 900 | 11-20 21:37 | P1 | .dll 34.33／.cs 9.00／.pdb 7.64 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | 2 处文件 · `docs/m1-nosl3c-interaction-completion.md`、`docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/m1-nosl3c-iig-completion-recovery` | 56.98 | 900 | 11-20 21:31 | P4 | .dll 34.32／.cs 9.00／.pdb 7.64 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | — |
| `logs/m1-nosl3c-iig-completion-draw` | 56.97 | 900 | 11-20 21:25 | P4 | .dll 34.32／.cs 8.99／.pdb 7.64 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | — |
| `logs/m1-nosl3c-iig-completion-diag2` | 56.96 | 900 | 11-20 21:21 | P4 | .dll 34.31／.cs 8.99／.pdb 7.64 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | — |
| `logs/m1-nosl3c-iig-certified` | 56.85 | 899 | 11-20 18:55 | P1 | .dll 34.31／.cs 8.99／.pdb 7.63 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | 3 处文件 · `docs/m1-nosl3c-interaction-completion.md`、`docs/m1-nosl3c-interaction-gap-resolution.md` |
| `logs/m1-nosl3c-iig-final` | 56.85 | 899 | 11-20 18:49 | P4 | .dll 34.31／.cs 8.99／.pdb 7.63 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | — |
| `logs/m1-nosl3c-iig-ordered` | 56.84 | 899 | 11-20 18:44 | P4 | .dll 34.31／.cs 8.99／.pdb 7.63 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | — |
| `logs/m1-nosl3c-iig-release` | 56.84 | 899 | 11-20 18:41 | P4 | .dll 34.31／.cs 8.99／.pdb 7.63 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | — |
| `logs/m1-nosl3c-iig-solver` | 56.84 | 899 | 11-20 18:38 | P4 | .dll 34.31／.cs 8.99／.pdb 7.63 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | — |
| `logs/m1-nosl3c-iid-solver` | 56.83 | 898 | 11-20 17:06 | P4 | .dll 34.30／.cs 8.99／.pdb 7.63 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | 3 处文件 · `docs/m1-nosl3c-hp-loss-training.md`、`docs/m1-nosl3c-solver-adapter-audit.md` |
| `logs/m1-nosl3c-iib-solver-v3` | 56.83 | 897 | 11-20 14:49 | P4 | .dll 34.30／.cs 8.99／.pdb 7.63 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | 1 处文件 · `docs/m1-nosl3c-training-admission.md` |
| `logs/m1-nosl3c-iib-solver-v2` | 56.83 | 897 | 11-20 14:42 | P4 | .dll 34.30／.cs 8.99／.pdb 7.63 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | — |
| `logs/ls2b-qualified` | 54.12 | 413 | 11-19 21:32 | P1 | .log 49.95／.jsonl 2.53／.sqlite 1.50 | `engine/game-_jrw6vxg/stdout.log` (1.91) | 1 处文件 · `docs/m1-ls2b-compositional-strategy-search.md` |
| `logs/m1-ls1-corrected` | 50.48 | 341 | 11-19 20:03 | P4 | .log 38.67／.json 9.75／.jsonl 2.05 | `engine/game-yd8nida6/stdout.log` (2.21) | — |
| `logs/m1-n2d-formal` | 49.60 | 261 | 11-19 17:34 | P4 | .json 34.39／.log 14.72／.jsonl 0.50 | `ledger.json` (33.71) | — |
| `logs/m1-p1` | 49.40 | 355 | 11-17 19:26 | P4 | .json 21.80／.log 17.36／.save 5.12 | `trial-5/hot-0/game-ewboehd9/stdout.log` (1.04) | 2 处文件 · `docs/m1-p1-hot-worker-experiment.md`、`scripts/m1_p1/build_probe.py` |
| `logs/m1-f3b-formal` | 48.28 | 350 | 11-18 17:59 | P4 | .log 46.22／.gz 0.80／.json 0.65 | `game-st4bsful/stdout.log` (1.84) | — |
| `logs/m1-b1-baseline` | 43.71 | 605 | 11-20 21:44 | P4 | .dll 16.86／.log 16.53／.gif 6.92 | `lib/sts2.dll` (10.15) | — |
| `logs/m1-d1-v1-w2` | 42.31 | 598 | 11-18 19:13 | P4 | .log 35.37／.json 6.64／.jsonl 0.29 | `manifest.json` (3.72) | 3 处文件 · `docs/m1-d2b-assisted-run-continuation.md`、`experiments/m1-d2a/test_native_choices.py` |
| `logs/m1-f5b` | 33.60 | 144 | 11-19 12:55 | P4 | .json 19.69／.log 13.32／.jsonl 0.59 | `development/results.json` (12.55) | 1 处文件 · `docs/m1-f5b-adaptive-strategy-search.md` |
| `logs/nosl3c-ib-final-resume` | 30.56 | 333 | 11-20 13:21 | P4 | .log 24.07／.sqlite 3.77／.gz 1.03 | `comparison/control/training.sqlite` (1.88) | — |
| `logs/m0-a1` | 30.26 | 2531 | 11-17 15:00 | P4 | .py 15.15／.pyc 11.83／.exe 2.49 | `venv/Lib/site-packages/pip/_vendor/rich/__pycache__/_emoji_codes.cpython-310.pyc` (0.34) | — |
| `logs/nosl3c-ib-matrix-batched` | 28.47 | 290 | 11-20 13:00 | P4 | .log 23.39／.sqlite 2.70／.gz 1.11 | `training.sqlite` (2.70) | — |
| `logs/nosl3c-ib-matrix-stock` | 28.46 | 294 | 11-20 12:57 | P4 | .log 23.39／.sqlite 2.70／.gz 1.11 | `training.sqlite` (2.70) | — |
| `logs/nosl3c-ib-matrix-micro` | 28.46 | 294 | 11-20 12:58 | P4 | .log 23.40／.sqlite 2.68／.gz 1.11 | `training.sqlite` (2.68) | — |
| `logs/nosl3c-ib-matrix-features` | 28.45 | 290 | 11-20 12:59 | P4 | .log 23.39／.sqlite 2.69／.gz 1.11 | `training.sqlite` (2.69) | — |
| `logs/nosl3c-ib-stock` | 28.44 | 289 | 11-20 12:50 | P4 | .log 23.39／.sqlite 2.68／.gz 1.11 | `training.sqlite` (2.68) | — |
| `logs/m1-f3a-formal` | 28.00 | 220 | 11-19 19:43 | P4 | .log 25.94／.json 1.80／.jsonl 0.26 | `game-xr9tu534/stdout.log` (2.50) | 6 处文件 · `docs/m1-f3b-first-win-search.md`、`docs/m1-ls1-learning-guided-search-loop.md` |
| `logs/m1-nosl3c-iib-solver` | 24.95 | 885 | 11-20 14:40 | P4 | .dll 10.05／.cs 8.99／.xml 5.81 | `source/.godot/mono/temp/obj/Release/PublicizedAssemblies/sts2.75EC4687F586508794CD45209C7558C2/sts2.dll` (10.05) | — |
| `logs/iih3-holdout-low` | 24.26 | 672 | 11-21 10:41 | P0 | .log 22.75／.sqlite 0.72／.json 0.41 | `engine/game-0xwjq3lc/stdout.log` (1.12) | — |
| `logs/nosl3c-iig-completion-independent` | 23.63 | 630 | 11-20 21:42 | P4 | .log 21.83／.sqlite 0.72／.json 0.71 | `engine/game-2vaecwx6/stdout.log` (1.12) | — |
| `logs/iih2-holdout` | 23.06 | 630 | 11-20 23:48 | P0 | .log 21.62／.sqlite 0.72／.jsonl 0.36 | `engine/game-azsyvu8w/stdout.log` (1.12) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/iih3-holdout` | 21.72 | 672 | 11-21 10:25 | P0 | .log 20.28／.sqlite 0.72／.json 0.36 | `engine/game-chjr3kll/stdout.log` (1.12) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/m1-f4` | 20.67 | 519 | 11-18 20:53 | P1 | .log 18.50／.jsonl 0.93／.json 0.73 | `formal-v1/shiv-hive-stocked/engine/game-7rvrg04e/stdout.log` (0.67) | 4 处文件 · `docs/m1-f4-route-quality-search.md`、`docs/m1-f5b-adaptive-strategy-search.md` |
| `logs/iih3-holdout-retry` | 20.48 | 660 | 11-21 10:31 | P0 | .log 19.11／.sqlite 0.71／.jsonl 0.33 | `engine/game-3qex65lz/stdout.log` (1.12) | — |
| `logs/m1-d1-v1-w1` | 20.32 | 233 | 11-18 18:28 | P4 | .log 15.83／.json 4.36／.jsonl 0.13 | `engine/game-12ovr90_/stdout.log` (2.53) | — |
| `logs/m1-d1-formal` | 19.19 | 217 | 11-18 18:20 | P4 | .log 15.16／.json 3.91／.jsonl 0.12 | `engine/game-cr7_nh2t/stdout.log` (2.53) | — |
| `logs/m1-f1-study2` | 18.90 | 209 | 11-18 15:31 | P4 | .log 13.09／.json 5.68／.jsonl 0.13 | `results.json` (2.99) | — |
| `logs/iih3-archive-retry` | 18.88 | 549 | 11-21 10:38 | P0 | .log 18.02／.json 0.56／.jsonl 0.30 | `engine/game-x9h3k88p/stdout.log` (0.83) | — |
| `logs/m1-f1-formal` | 18.00 | 192 | 11-18 15:38 | P4 | .log 12.18／.json 5.70／.jsonl 0.12 | `results.json` (3.01) | 2 处文件 · `docs/m1-f2-combat-action-coverage.md`、`docs/m1-f3b-first-win-search.md` |
| `logs/nosl3c-iig-completion-archive` | 17.94 | 521 | 11-20 21:40 | P4 | .log 16.74／.json 0.92／.jsonl 0.28 | `engine/game-i4k4fwim/stdout.log` (0.83) | — |
| `logs/iih-baseline` | 17.94 | 521 | 11-20 23:09 | P4 | .log 16.74／.json 0.92／.jsonl 0.28 | `engine/game-hnqxbxdz/stdout.log` (0.83) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/nosl3c-iig-certified-archive` | 17.86 | 521 | 11-20 18:57 | P4 | .log 16.72／.json 0.86／.jsonl 0.28 | `engine/game-qht3gtx3/stdout.log` (0.83) | — |
| `logs/nosl3c-iig-guarded-archive` | 17.84 | 521 | 11-20 18:52 | P4 | .log 16.72／.json 0.84／.jsonl 0.28 | `engine/game-hagsyzqa/stdout.log` (0.83) | — |
| `logs/nosl3c-iig-archive-final` | 17.84 | 521 | 11-20 18:46 | P4 | .log 16.72／.json 0.84／.jsonl 0.28 | `engine/game-27de239v/stdout.log` (0.83) | — |
| `logs/nosl3c-iif-frozen-final` | 17.67 | 520 | 11-20 18:21 | P4 | .log 16.68／.json 0.71／.jsonl 0.28 | `engine/game-nt0s82n3/stdout.log` (0.83) | — |
| `logs/nosl3c-iif-frozen` | 17.67 | 520 | 11-20 18:18 | P4 | .log 16.68／.json 0.71／.jsonl 0.28 | `engine/game-huqw6jc_/stdout.log` (0.83) | — |
| `logs/m1-d1-hot` | 17.56 | 98 | 11-18 18:27 | P4 | .json 8.01／.log 6.39／.save 1.84 | `hot-0-0/game-tjm2x46d/stdout.log` (1.04) | — |
| `logs/iih2-archive` | 17.35 | 521 | 11-20 23:47 | P0 | .log 16.51／.json 0.56／.jsonl 0.28 | `engine/game-kvhitbo5/stdout.log` (0.83) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/iih1-archive` | 17.35 | 521 | 11-20 23:25 | P4 | .log 16.51／.json 0.56／.jsonl 0.28 | `engine/game-hmjaq51w/stdout.log` (0.83) | — |
| `logs/m0-v5c` | 17.26 | 180 | 11-17 13:18 | P4 | .dll 14.56／.json 1.21／.il 0.64 | `probe-build/lib/sts2.dll` (10.15) | — |
| `logs/iih3-cold` | 16.22 | 350 | 11-21 10:27 | P0 | .log 14.76／.sqlite 1.02／.jsonl 0.23 | `training.sqlite` (1.02) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/m1-n2a1-timed` | 15.68 | 37 | 11-19 16:01 | P4 | .json 11.03／.log 4.49／.jsonl 0.16 | `results.json` (11.03) | — |
| `logs/m1-n2a1-measured` | 15.67 | 37 | 11-19 15:58 | P4 | .json 11.02／.log 4.49／.jsonl 0.16 | `results.json` (11.02) | — |
| `logs/nosl3c-stress` | 15.29 | 161 | 11-20 11:58 | P4 | .log 12.07／.sqlite 1.88／.gz 0.51 | `engine/game-xkz5eywx/stdout.log` (2.52) | — |
| `logs/nosl3c-resume-proof` | 15.21 | 145 | 11-20 11:59 | P4 | .log 11.99／.sqlite 1.88／.gz 0.51 | `control/engine/game-0k5y9zyt/stdout.log` (2.52) | — |
| `logs/nosl3c-iie-midstop` | 15.15 | 177 | 11-20 17:29 | P4 | .log 13.45／.sqlite 1.29／.json 0.21 | `engine/game-amy1b93u/stdout.log` (2.36) | — |
| `logs/nosl3c-iie-release-resume` | 15.14 | 174 | 11-20 17:26 | P4 | .log 13.45／.sqlite 1.29／.json 0.21 | `engine/game-kxzwfghf/stdout.log` (2.67) | — |
| `logs/iih3-resume-low` | 15.13 | 353 | 11-21 10:38 | P0 | .log 13.72／.sqlite 1.03／.jsonl 0.22 | `training.sqlite` (1.03) | — |
| `logs/nosl3c-iie-release-control` | 15.09 | 167 | 11-20 17:26 | P4 | .log 13.40／.sqlite 1.29／.json 0.21 | `engine/game-x4z6ewl1/stdout.log` (2.58) | — |
| `logs/nosl3c-iie-cold` | 15.06 | 192 | 11-20 17:29 | P4 | .log 13.37／.sqlite 1.29／.json 0.21 | `engine/game-5b2gkdy3/stdout.log` (2.36) | — |
| `logs/m1-b2-benchmark` | 14.67 | 123 | 11-17 17:17 | P4 | .log 12.26／.jsonl 2.35／.save 0.05 | `engines/game-0z8efu7i/stdout.log` (0.32) | 4 处文件 · `docs/m1-b2-benchmark.md`、`docs/m1-d1-native-combat-data-factory.md` |
| `logs/m1-f2-formal` | 14.44 | 165 | 11-18 16:09 | P4 | .log 8.81／.json 5.55／.jsonl 0.09 | `results.json` (4.61) | — |
| `logs/m1-n1-formal` | 13.91 | 509 | 11-19 15:03 | P4 | .log 13.14／.gz 0.61／.jsonl 0.17 | `results.jsonl.gz` (0.61) | — |
| `logs/m1-i3` | 13.30 | 25 | 11-18 10:36 | P4 | .log 10.90／.json 1.84／.jsonl 0.56 | `run_1-verified/game-l97uwj08/stdout.log` (5.93) | 1 处文件 · `docs/m1-i3-potion-integration.md` |
| `logs/m1-f3a-resample` | 13.16 | 60 | 11-18 16:51 | P4 | .log 11.78／.json 1.27／.jsonl 0.11 | `game-m8oqic1t/stdout.log` (2.50) | — |
| `logs/m1-d1-testdeps` | 11.74 | 1046 | 11-18 18:28 | P4 | .py 6.55／.pyc 4.70／.exe 0.31 | `typing_extensions.py` (0.16) | — |
| `logs/iig-completion-test-deps` | 11.54 | 1030 | 11-20 21:43 | P4 | .py 6.44／.pyc 4.62／.exe 0.31 | `typing_extensions.py` (0.16) | — |
| `logs/nosl3c-benchmark` | 10.57 | 169 | 11-20 11:54 | P4 | .log 10.14／.jsonl 0.36／.json 0.07 | `engine/game-nv6elk1a/stdout.log` (1.25) | — |
| `logs/ls2b-evidence-final` | 9.68 | 166 | 11-20 18:43 | P4 | .log 7.58／.gz 1.58／.jsonl 0.40 | `report-audit.jsonl.gz` (0.85) | — |
| `logs/nosl3a-formal-v1` | 9.60 | 411 | 11-19 23:07 | P4 | .log 7.29／.gz 2.07／.jsonl 0.18 | `engine/game-0xpfpj4w/stdout.log` (0.41) | — |
| `logs/nosl3c-iid-mapped-independent` | 9.47 | 311 | 11-20 17:04 | P4 | .log 8.61／.sqlite 0.40／.json 0.33 | `engine/game-kwwmduvs/stdout.log` (0.56) | — |
| `logs/nosl3c-iid-release-independent` | 9.47 | 311 | 11-20 17:07 | P0 | .log 8.61／.sqlite 0.40／.json 0.33 | `engine/game-crgtremw/stdout.log` (0.56) | 4 处文件 · `docs/m1-nosl3c-interaction-completion.md`、`docs/m1-nosl3c-interaction-gap-resolution.md` |
| `logs/nosl3c-tests` | 9.29 | 260 | 11-20 21:45 | P4 | .log 8.97／.jsonl 0.32 | `engine/game-ra523pl5/stdout.log` (0.47) | 1 处文件 · `experiments/m1-nosl3c/test_nosl3c.py` |
| `logs/ls2a-native` | 9.09 | 228 | 11-19 20:41 | P4 | .log 5.55／.json 3.48／.jsonl 0.06 | `manifest.json` (1.05) | — |
| `logs/m1-nosl3c-iig-completion-diagnose` | 9.05 | 868 | 11-20 21:19 | P4 | .cs 8.99／.json 0.05／.csproj 0.01 | `source/src/Runtime/SolverController.cs` (0.17) | — |
| `logs/nosl3c-iid-independent-final` | 8.87 | 311 | 11-20 17:00 | P4 | .log 8.00／.sqlite 0.40／.json 0.35 | `engine/game-d1vqrjrh/stdout.log` (0.56) | — |
| `logs/iih3-resume-final` | 8.84 | 336 | 11-21 10:29 | P0 | .log 7.92／.sqlite 0.66／.jsonl 0.14 | `engine/game-sglir6i5/stdout.log` (0.94) | — |
| `logs/m1-n2d-native` | 8.77 | 25 | 11-19 17:35 | P4 | .log 8.49／.jsonl 0.23／.json 0.05 | `engine/game-jayrrlet/stdout.log` (1.74) | — |
| `logs/nosl3c-iid-independent` | 8.67 | 320 | 11-20 16:59 | P4 | .log 8.00／.sqlite 0.40／.json 0.13 | `engine/game-9775v10g/stdout.log` (0.56) | — |
| `logs/m1-d2b` | 8.31 | 134 | 11-18 19:41 | P4 | .log 6.75／.json 1.48／.jsonl 0.06 | `pytest/test_archived_potion_and_choic0/engine/game-67_mrd47/stdout.log` (0.66) | 2 处文件 · `docs/m1-d2b-assisted-run-continuation.md`、`experiments/m1-d2b/test_rescue.py` |
| `logs/nosl3c-complete-benchmark` | 7.74 | 149 | 11-20 12:14 | P4 | .log 5.17／.sqlite 1.38／.pt 0.69 | `resident/engine/game-9ny78olt/stdout.log` (0.85) | — |
| `logs/iih3-resume` | 7.53 | 182 | 11-21 10:24 | P0 | .log 6.74／.sqlite 0.58／.json 0.11 | `engine/game-pa_61x7a/stdout.log` (0.94) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/nosl3c-iie-resume` | 6.77 | 69 | 11-20 17:22 | P4 | .log 6.08／.sqlite 0.54／.jsonl 0.08 | `engine/game-7m0sgqlc/stdout.log` (1.88) | — |
| `logs/m1-i1` | 6.77 | 62 | 11-18 10:37 | P4 | .log 4.99／.json 1.08／.jsonl 0.71 | `trace.json` (1.08) | 2 处文件 · `docs/m1-i1-combat-integration.md`、`experiments/m1-i1/run.py` |
| `logs/m1-f3d-b` | 6.57 | 154 | 11-18 20:34 | P4 | .log 6.10／.json 0.21／.jsonl 0.19 | `formal/shiv-hive-stocked/engine/game-aphwk8ap/stdout.log` (0.67) | 2 处文件 · `docs/m1-f3d-b-prediction-compatibility.md`、`experiments/m1-f3d-b/test_compatibility.py` |
| `logs/m1-f3d-a` | 6.56 | 181 | 11-18 20:12 | P4 | .log 5.87／.json 0.51／.jsonl 0.15 | `formal/shiv-hive-stocked/engine/game-0pv5w5_d/stdout.log` (0.67) | 2 处文件 · `docs/m1-f3d-a-survivor-choice.md`、`experiments/m1-f3d-a/test_survivor.py` |
| `logs/nosl3c-iid-release-frozen` | 5.87 | 192 | 11-20 17:07 | P4 | .log 5.19／.sqlite 0.37／.json 0.21 | `engine/game-qyxlwihf/stdout.log` (0.55) | — |
| `logs/nosl3c-iig-completion-resample-update` | 5.69 | 152 | 11-20 21:52 | P4 | .log 4.78／.sqlite 0.56／.json 0.27 | `engine/game-tejj62z4/stdout.log` (0.72) | — |
| `logs/nosl3c-iig-completion-pair16` | 5.62 | 158 | 11-20 21:39 | P4 | .log 5.07／.sqlite 0.35／.json 0.12 | `engine/game-omx0j60w/stdout.log` (0.81) | — |
| `logs/nosl3c-iig-independent` | 5.62 | 158 | 11-20 18:47 | P4 | .log 5.07／.sqlite 0.35／.json 0.12 | `engine/game-oqzz3hyi/stdout.log` (0.81) | — |
| `logs/nosl3c-iig-certified-independent` | 5.62 | 158 | 11-20 18:58 | P4 | .log 5.07／.sqlite 0.35／.json 0.12 | `engine/game-1_lxd0st/stdout.log` (0.81) | — |
| `logs/iih2-pair16` | 5.56 | 158 | 11-20 23:46 | P0 | .log 5.04／.sqlite 0.35／.json 0.08 | `engine/game-gj7datv0/stdout.log` (0.81) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/nosl3c-iid-mapped-frozen` | 5.47 | 185 | 11-20 17:03 | P4 | .log 4.80／.sqlite 0.37／.json 0.21 | `engine/game-zautb_e4/stdout.log` (0.55) | — |
| `logs/nosl3c-iig-completion-resample` | 5.46 | 152 | 11-20 21:39 | P4 | .log 4.78／.sqlite 0.34／.json 0.27 | `engine/game-2ua8yd_7/stdout.log` (0.72) | — |
| `logs/m1-n2c-native` | 5.44 | 25 | 11-19 17:17 | P4 | .log 5.25／.jsonl 0.14／.json 0.05 | `engine/game-egw8yzf3/stdout.log` (1.05) | — |
| `logs/m1-d2a` | 5.38 | 66 | 11-18 18:56 | P4 | .log 4.42／.json 0.92／.jsonl 0.03 | `reruns/engine/game-_yc4nk_6/stdout.log` (1.01) | 3 处文件 · `docs/m1-d2b-assisted-run-continuation.md`、`experiments/m1-d2a/test_native_choices.py` |
| `logs/nosl3a-tests` | 5.36 | 354 | 11-20 21:44 | P4 | .log 5.09／.jsonl 0.28 | `engine/game-di5pntzf/stdout.log` (0.16) | 1 处文件 · `experiments/m1-nosl3a/test_nosl3a.py` |
| `logs/nosl3b-pilot-v1` | 5.27 | 142 | 11-20 11:13 | P4 | .log 4.61／.gz 0.52／.jsonl 0.11 | `pilot.json.gz` (0.45) | — |
| `logs/m1-f1-pilot` | 5.25 | 101 | 11-18 15:26 | P4 | .log 3.45／.json 1.76／.jsonl 0.04 | `results.json` (0.73) | — |
| `logs/nosl3c-iie-broad` | 5.19 | 133 | 11-20 17:27 | P0 | .log 4.41／.sqlite 0.57／.json 0.13 | `engine/game-j0qrdpiz/stdout.log` (0.93) | 4 处文件 · `docs/m1-nosl3c-interaction-completion.md`、`docs/m1-nosl3c-interaction-gap-resolution.md` |
| `logs/nosl3c-iig-completion-recovery-resample` | 5.18 | 152 | 11-20 21:32 | P4 | .log 4.53／.sqlite 0.34／.json 0.24 | `engine/game-hajka7zb/stdout.log` (0.69) | — |
| `logs/iih3-archive-serial` | 5.15 | 179 | 11-21 10:28 | P0 | .log 4.90／.json 0.15／.jsonl 0.10 | `engine/game-_v2tbt_g/stdout.log` (0.44) | — |
| `logs/ls2a-cache-proof` | 5.14 | 3 | 11-19 20:54 | P4 | .sqlite 5.00／.json 0.14／(none) 0.00 | `search.sqlite` (5.00) | — |
| `logs/ls2a-catalog-drift` | 5.07 | 3 | 11-19 20:59 | P4 | .sqlite 5.00／.json 0.08／(none) 0.00 | `search.sqlite` (5.00) | — |
| `logs/m1-n2a2-probe` | 5.03 | 29 | 11-19 16:20 | P4 | .log 4.48／.json 0.44／.jsonl 0.11 | `engine/game-u72sfnk2/stdout.log` (1.10) | — |
| `logs/m1-n2a-measured` | 4.94 | 37 | 11-19 15:31 | P4 | .json 3.31／.log 1.52／.jsonl 0.11 | `results.json` (3.31) | — |
| `logs/m1-n2a-formal` | 4.89 | 37 | 11-19 15:29 | P4 | .json 3.30／.log 1.48／.jsonl 0.11 | `results.json` (3.30) | — |
| `logs/nosl3c-iid-frozen-final` | 4.79 | 185 | 11-20 17:00 | P4 | .log 4.11／.sqlite 0.37／.json 0.24 | `engine/game-_v8rci8t/stdout.log` (0.53) | — |
| `logs/nosl3c-iid-frozen` | 4.64 | 194 | 11-20 16:58 | P4 | .log 4.11／.sqlite 0.37／.jsonl 0.07 | `engine/game-vx97us0d/stdout.log` (0.53) | — |
| `logs/m1-e3` | 4.64 | 44 | 11-19 12:29 | P4 | .json 2.59／.log 1.96／.jsonl 0.09 | `formal/results.json` (1.80) | 1 处文件 · `docs/m1-e3-terminal-semantic-audit.md` |
| `logs/m1-s2c` | 4.42 | 444 | 11-18 21:36 | P4 | .gz 3.84／.json 0.57／.py 0.01 | `formal-v2/report.json` (0.19) | 4 处文件 · `docs/m1-f5a-fast-solver-throughput.md`、`docs/m1-s2c-cross-root-benchmark.md` |
| `logs/iih2-rewards-power` | 4.41 | 57 | 11-20 23:51 | P0 | .log 4.13／.json 0.24／.jsonl 0.04 | `engine/game-rhgcjdm1/stdout.log` (0.89) | — |
| `logs/m1-f3b-checks-final` | 4.15 | 62 | 11-18 18:01 | P4 | .log 3.52／.json 0.59／.jsonl 0.04 | `game-2eo_j09p/stdout.log` (0.65) | — |
| `logs/m1-f3b-pilot2` | 3.91 | 56 | 11-18 17:52 | P4 | .log 3.43／.json 0.40／.gz 0.05 | `game-uzagz93b/stdout.log` (0.65) | — |
| `logs/m1-s2a` | 3.89 | 171 | 11-18 19:55 | P1 | .log 2.94／.json 0.82／.jsonl 0.11 | `formal/records.json` (0.73) | 7 处文件 · `docs/m1-f3d-b-prediction-compatibility.md`、`docs/m1-f4-route-quality-search.md` |
| `logs/nosl3c-iid-release-routes` | 3.84 | 132 | 11-20 17:08 | P4 | .log 3.61／.json 0.15／.jsonl 0.07 | `engine/game-bwf6v5xv/stdout.log` (0.44) | — |
| `logs/nosl3c-iid-mapped-routes` | 3.84 | 132 | 11-20 17:04 | P4 | .log 3.61／.json 0.15／.jsonl 0.07 | `engine/game-94ovfjb9/stdout.log` (0.44) | — |
| `logs/nosl3c-iib-scan` | 3.82 | 109 | 11-20 14:51 | P4 | .log 3.58／.json 0.18／.jsonl 0.06 | `engine/game-mep9_e4s/stdout.log` (0.38) | — |
| `logs/nosl3c-ib-smoke` | 3.73 | 67 | 11-20 12:55 | P4 | .log 3.14／.sqlite 0.32／.jsonl 0.12 | `engine/game-lfge9v85/stdout.log` (0.56) | — |
| `logs/m1-d1-resume` | 3.67 | 64 | 11-18 18:32 | P4 | .log 3.04／.json 0.59／.jsonl 0.03 | `engine/game-5zd8ie7g/stdout.log` (2.26) | — |
| `logs/nosl3c-iic-random-final` | 3.65 | 175 | 11-20 16:41 | P0 | .log 2.99／.sqlite 0.35／.json 0.26 | `engine/game-eh3ni2mj/stdout.log` (0.43) | 5 处文件 · `docs/m1-nosl3c-interaction-completion.md`、`docs/m1-nosl3c-interaction-gap-resolution.md` |
| `logs/nosl3c-iic-random` | 3.65 | 175 | 11-20 16:40 | P4 | .log 2.99／.sqlite 0.35／.json 0.25 | `engine/game-ratdlx6k/stdout.log` (0.43) | — |
| `logs/m1-b1a` | 3.59 | 88 | 11-19 12:43 | P4 | .log 3.14／.json 0.32／.jsonl 0.13 | `final/engine/game-oth0cxq8/stdout.log` (0.53) | 1 处文件 · `docs/m1-b1a-artificial-combat-root.md` |
| `logs/m1-d1-meter` | 3.57 | 45 | 11-18 18:31 | P4 | .log 2.96／.json 0.59／.jsonl 0.03 | `engine/game-yyed5yxn/stdout.log` (2.26) | — |
| `logs/iih2-rewards-final` | 3.55 | 57 | 11-20 23:50 | P0 | .log 3.28／.json 0.23／.jsonl 0.04 | `engine/game-qu8emqiq/stdout.log` (0.69) | — |
| `logs/m1-d1-pilot` | 3.55 | 45 | 11-18 18:26 | P4 | .log 2.94／.json 0.59／.jsonl 0.03 | `engine/game-kat1hoow/stdout.log` (2.26) | — |
| `logs/nosl3c-iig-archive` | 3.49 | 248 | 11-20 18:43 | P4 | .log 3.29／.json 0.11／.jsonl 0.09 | `engine/game-lgz_n7u0/stdout.log` (0.13) | — |
| `logs/nosl3c-iib-scan-retained` | 3.30 | 109 | 11-20 16:21 | P4 | .log 3.01／.json 0.23／.jsonl 0.06 | `coverage.json` (0.23) | — |
| `logs/nosl3c-iib-scan-weak` | 3.29 | 109 | 11-20 14:54 | P4 | .log 3.01／.json 0.22／.jsonl 0.06 | `engine/game-24x90ohv/stdout.log` (0.22) | — |
| `logs/nosl3c-iid-routes` | 3.25 | 141 | 11-20 17:00 | P4 | .log 3.02／.json 0.18／.jsonl 0.06 | `engine/game-4j5vwcp0/stdout.log` (0.44) | — |
| `logs/nosl3c-iig-completion-ls2b-native` | 3.19 | 62 | 11-21 10:27 | P4 | .log 3.03／.jsonl 0.16 | `engine/game-8xvwiu1m/stdout.log` (0.33) | — |
| `logs/m1-n2a1-audit-final` | 3.18 | 25 | 11-19 16:00 | P4 | .log 3.04／.jsonl 0.10／.json 0.04 | `engine/game-dg0kezu7/stdout.log` (0.95) | — |
| `logs/m1-p2` | 3.05 | 217 | 11-19 11:33 | P4 | .log 2.87／.jsonl 0.10／.json 0.07 | `load/engine/game-2rmq3zpz/stdout.log` (0.09) | 1 处文件 · `docs/m1-p2-independent-prediction-host.md` |
| `logs/m1-i2` | 2.90 | 9 | 11-18 10:25 | P4 | .log 2.43／.json 0.32／.jsonl 0.16 | `game-t8t2w4eu/stdout.log` (1.20) | 2 处文件 · `docs/m1-i2-reusable-combat-integration.md`、`experiments/m1-i2/run.py` |
| `logs/m1-s2b` | 2.73 | 339 | 11-18 21:15 | P4 | .gz 1.42／.json 1.30／.log 0.00 | `formal/plan.json` (0.66) | 13 处文件 · `docs/m1-s2b-synthetic-combat-bank.md`、`docs/m1-s2c-cross-root-benchmark.md` |
| `logs/ls2b-check` | 2.49 | 54 | 11-19 21:45 | P4 | .log 2.36／.jsonl 0.13 | `engine/game-i5aha2zx/stdout.log` (0.33) | — |
| `logs/m1-n2a1-native` | 2.48 | 19 | 11-19 15:58 | P4 | .log 2.37／.jsonl 0.08／.json 0.03 | `engine/game-ahrtpidf/stdout.log` (0.95) | — |
| `logs/nosl3c-iig-completion-final-prefix` | 2.44 | 71 | 11-20 21:41 | P4 | .log 2.30／.json 0.11／.jsonl 0.04 | `engine/game-6viyf8e9/stdout.log` (0.65) | — |
| `logs/m1-s1` | 2.44 | 81 | 11-18 19:41 | P4 | .log 2.02／.json 0.36／.jsonl 0.05 | `pytest/test_archived_potion_and_choic0/engine/game-gl4hjn9u/stdout.log` (0.66) | 2 处文件 · `docs/m1-s1-synthetic-combat-feasibility.md`、`experiments/m1-s1/test_synthetic.py` |
| `logs/m1-review-traces` | 2.40 | 11 | 11-17 15:17 | P4 | .jsonl 2.39／.json 0.01／.log 0.00 | `baseline-run_4/20261117_151713_Regent_run_4.jsonl` (1.00) | — |
| `logs/m1-f5a` | 2.39 | 258 | 11-19 11:21 | P4 | .gz 1.54／.log 0.81／.json 0.03 | `retry/labels/ce0b985532a91b53bcba139e6e767587579d1dc870cfe926338981cc13fc6726.json.gz` (0.08) | 1 处文件 · `docs/m1-f5a-fast-solver-throughput.md` |
| `logs/m1-nosl3c-iig-build` | 2.35 | 84 | 11-20 18:37 | P4 | .dll 1.15／.pdb 0.48／.cs 0.37 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.40) | — |
| `logs/m1-nosl3c-iih-reward-build` | 2.35 | 84 | 11-20 23:48 | P4 | .dll 1.15／.pdb 0.48／.cs 0.37 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.40) | — |
| `logs/m1-nosl3c-iif-build` | 2.35 | 84 | 11-20 18:21 | P4 | .dll 1.15／.pdb 0.48／.cs 0.37 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.40) | — |
| `logs/m1-nosl3c-iig-completion-build` | 2.35 | 84 | 11-20 21:22 | P4 | .dll 1.15／.pdb 0.48／.cs 0.37 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.40) | — |
| `logs/m1-nosl3c-iid-build` | 2.34 | 84 | 11-20 17:02 | P4 | .dll 1.14／.pdb 0.48／.cs 0.37 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.40) | — |
| `logs/nosl3c-iig-completion-resume` | 2.34 | 77 | 11-20 21:47 | P4 | .log 1.38／.sqlite 0.86／.json 0.07 | `training.sqlite` (0.86) | — |
| `logs/nosl3c-iig-completion-release-resume` | 2.34 | 77 | 11-20 22:06 | P4 | .log 1.38／.sqlite 0.86／.json 0.07 | `training.sqlite` (0.86) | — |
| `logs/nosl3c-iig-completion-control` | 2.34 | 76 | 11-20 21:39 | P4 | .log 1.38／.sqlite 0.86／.json 0.07 | `training.sqlite` (0.86) | — |
| `logs/nosl3c-iig-completion-release-control` | 2.34 | 76 | 11-20 22:05 | P4 | .log 1.38／.sqlite 0.86／.json 0.07 | `training.sqlite` (0.86) | — |
| `logs/nosl3c-iig-certified-resume` | 2.34 | 77 | 11-20 18:57 | P4 | .log 1.38／.sqlite 0.86／.json 0.07 | `training.sqlite` (0.86) | — |
| `logs/nosl3c-iig-resume` | 2.34 | 77 | 11-20 18:47 | P4 | .log 1.38／.sqlite 0.86／.json 0.07 | `training.sqlite` (0.86) | — |
| `logs/nosl3c-iig-guarded-control` | 2.34 | 76 | 11-20 18:53 | P4 | .log 1.38／.sqlite 0.86／.json 0.07 | `training.sqlite` (0.86) | — |
| `logs/nosl3c-iig-guarded-resume` | 2.34 | 76 | 11-20 18:52 | P4 | .log 1.38／.sqlite 0.86／.json 0.07 | `training.sqlite` (0.86) | — |
| `logs/nosl3c-iig-certified-control` | 2.34 | 76 | 11-20 18:57 | P4 | .log 1.38／.sqlite 0.86／.json 0.07 | `training.sqlite` (0.86) | — |
| `logs/nosl3c-iig-release-resume` | 2.34 | 76 | 11-20 19:02 | P4 | .log 1.38／.sqlite 0.86／.json 0.07 | `training.sqlite` (0.86) | — |
| `logs/nosl3c-iig-control` | 2.34 | 76 | 11-20 18:47 | P4 | .log 1.38／.sqlite 0.86／.json 0.07 | `training.sqlite` (0.86) | — |
| `logs/nosl3c-iig-release-control` | 2.34 | 76 | 11-20 19:02 | P4 | .log 1.38／.sqlite 0.86／.json 0.07 | `training.sqlite` (0.86) | — |
| `logs/nosl3c-iid-paired` | 2.34 | 196 | 11-20 16:57 | P4 | .log 1.82／.sqlite 0.37／.json 0.07 | `training.sqlite` (0.37) | — |
| `logs/m1-nosl3c-iib-build` | 2.33 | 83 | 11-20 14:48 | P4 | .dll 1.13／.pdb 0.48／.cs 0.37 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.39) | — |
| `logs/ls2a-qualified-serial` | 2.31 | 86 | 11-19 20:39 | P4 | .log 2.01／.json 0.14／.sqlite 0.13 | `engine/game-9adedis_/stdout.log` (0.36) | — |
| `logs/ls2a-qualified-parallel` | 2.31 | 86 | 11-19 20:40 | P4 | .log 2.01／.json 0.14／.sqlite 0.13 | `engine/game-4o8wvhzw/stdout.log` (0.36) | — |
| `logs/nosl3c-iig-completion-native-prefix` | 2.31 | 71 | 11-20 21:34 | P4 | .log 2.17／.json 0.11／.jsonl 0.03 | `engine/game-k57w0eke/stdout.log` (0.65) | — |
| `logs/m1-nosl3c-iia-build` | 2.29 | 82 | 11-20 14:16 | P4 | .dll 1.11／.pdb 0.47／.cs 0.36 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.38) | — |
| `logs/m1-nosl3c-build` | 2.28 | 82 | 11-20 11:50 | P4 | .dll 1.10／.pdb 0.47／.cs 0.36 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.38) | 3 处文件 · `experiments/m1-nosl3c-ib/runner.py`、`experiments/m1-nosl3c/run.py` |
| `logs/m1-nosl3a-build` | 2.27 | 82 | 11-19 22:55 | P4 | .dll 1.10／.pdb 0.47／.cs 0.36 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.38) | 2 处文件 · `experiments/m1-nosl3a/test_nosl3a.py`、`experiments/m1-nosl3b/test_nosl3b.py` |
| `logs/iih2-integration` | 2.27 | 76 | 11-20 23:47 | P0 | .log 1.35／.sqlite 0.86／.jsonl 0.03 | `training.sqlite` (0.86) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/iih2-cold` | 2.27 | 76 | 11-20 23:48 | P0 | .log 1.35／.sqlite 0.86／.jsonl 0.03 | `training.sqlite` (0.86) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/m1-n2e-build` | 2.22 | 82 | 11-19 18:01 | P4 | .dll 1.05／.pdb 0.46／.cs 0.35 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.36) | 1 处文件 · `experiments/m1-n2e/extract.py` |
| `logs/m1-n2a1-build` | 2.20 | 80 | 11-19 15:58 | P4 | .dll 1.04／.pdb 0.46／.cs 0.35 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.35) | 1 处文件 · `experiments/m1-n2a1/build.py` |
| `logs/m1-n2a2-build` | 2.20 | 80 | 11-19 16:12 | P4 | .dll 1.04／.pdb 0.46／.cs 0.35 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.35) | 1 处文件 · `experiments/m1-n2a2/build.py` |
| `logs/m1-ls2b-build` | 2.19 | 81 | 11-19 21:24 | P4 | .dll 1.03／.pdb 0.46／.cs 0.35 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.35) | 1 处文件 · `experiments/m1-ls2b/build.py` |
| `logs/m1-n2a-build` | 2.16 | 79 | 11-19 15:31 | P4 | .dll 1.01／.pdb 0.45／.cs 0.35 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.34) | 1 处文件 · `experiments/m1-n2a/build.py` |
| `logs/m1-ls2a-build` | 2.14 | 80 | 11-19 20:31 | P4 | .dll 1.00／.pdb 0.45／.cs 0.34 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.34) | 1 处文件 · `experiments/m1-ls2a/build.py` |
| `logs/m1-f6a-build` | 2.14 | 80 | 11-19 13:22 | P4 | .dll 1.00／.pdb 0.45／.cs 0.34 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.34) | 1 处文件 · `experiments/m1-f6a/build_probe.py` |
| `logs/m1-n1-build` | 2.11 | 79 | 11-19 14:55 | P4 | .dll 0.98／.pdb 0.44／.cs 0.34 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.33) | 1 处文件 · `experiments/m1-n1/build.py` |
| `logs/m1-f3b-checks` | 2.11 | 40 | 11-18 18:00 | P4 | .log 1.73／.json 0.37／.jsonl 0.01 | `game-zcak8ks_/stdout.log` (0.54) | 1 处文件 · `docs/m1-f3b-first-win-search.md` |
| `logs/m1-ls1-build` | 2.11 | 78 | 11-19 19:46 | P4 | .dll 0.98／.pdb 0.44／.cs 0.34 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.33) | 1 处文件 · `experiments/m1-ls1/build.py` |
| `logs/m1-s3b-build` | 2.10 | 78 | 11-19 14:02 | P4 | .dll 0.97／.pdb 0.44／.cs 0.34 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.33) | 1 处文件 · `experiments/m1-s3b/build_host.py` |
| `logs/m1-s3a-build` | 2.10 | 78 | 11-19 13:47 | P4 | .dll 0.97／.pdb 0.44／.cs 0.34 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.33) | 1 处文件 · `experiments/m1-s3a/build_host.py` |
| `logs/m1-b1b-build` | 2.10 | 78 | 11-19 13:07 | P4 | .dll 0.97／.pdb 0.44／.cs 0.34 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.33) | 1 处文件 · `experiments/m1-b1b/build_probe.py` |
| `logs/m1-b1a-build` | 2.09 | 78 | 11-19 12:40 | P4 | .dll 0.97／.pdb 0.44／.cs 0.34 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.32) | 1 处文件 · `experiments/m1-b1a/build_probe.py` |
| `logs/m1-p2-build` | 2.09 | 78 | 11-19 11:31 | P4 | .dll 0.97／.pdb 0.44／.cs 0.34 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.32) | 1 处文件 · `experiments/m1-p2/build_probe.py` |
| `logs/m1-f5b-build` | 2.08 | 78 | 11-19 12:52 | P4 | .dll 0.96／.pdb 0.44／.cs 0.34 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.32) | 1 处文件 · `experiments/m1-f5b/build_probe.py` |
| `logs/m1-e3f-build` | 2.08 | 77 | 11-19 13:34 | P4 | .dll 0.96／.pdb 0.43／.cs 0.33 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.32) | 1 处文件 · `experiments/m1-e3f/build_host.py` |
| `logs/m1-f4-build` | 2.07 | 77 | 11-18 21:03 | P4 | .dll 0.96／.pdb 0.43／.cs 0.33 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.32) | 1 处文件 · `experiments/m1-f4/build.py` |
| `logs/m1-f3d-b-build` | 2.03 | 76 | 11-18 20:31 | P4 | .dll 0.93／.pdb 0.42／.cs 0.33 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.31) | 1 处文件 · `experiments/m1-f3d-b/build.py` |
| `logs/m1-f3d-a-build` | 2.02 | 76 | 11-18 20:07 | P4 | .dll 0.92／.pdb 0.42／.cs 0.33 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.30) | 1 处文件 · `experiments/m1-f3d-a/build.py` |
| `logs/m1-s2a-build` | 2.02 | 76 | 11-18 19:49 | P4 | .dll 0.92／.pdb 0.42／.cs 0.32 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.30) | 1 处文件 · `docs/m1-f3d-a-survivor-choice.md` |
| `logs/m1-s1-build` | 1.99 | 75 | 11-18 19:39 | P4 | .dll 0.90／.pdb 0.42／.cs 0.32 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.29) | — |
| `logs/nosl3a-pilot-2` | 1.97 | 39 | 11-19 23:02 | P4 | .gz 1.42／.log 0.52／.jsonl 0.01 | `id-trained.json.gz` (0.23) | — |
| `logs/m1-d2a-build` | 1.96 | 75 | 11-18 18:53 | P4 | .dll 0.89／.pdb 0.41／.cs 0.32 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.29) | — |
| `logs/nosl3a-pilot-1` | 1.96 | 39 | 11-19 23:00 | P4 | .gz 1.42／.log 0.52／.jsonl 0.01 | `id-initial.json.gz` (0.23) | — |
| `logs/m1-n1-real-build` | 1.96 | 75 | 11-19 15:04 | P4 | .dll 0.88／.pdb 0.41／.cs 0.32 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.29) | 1 处文件 · `experiments/m1-n1/build.py` |
| `logs/m1-d1-meter-build` | 1.95 | 74 | 11-18 18:30 | P4 | .dll 0.88／.pdb 0.41／.cs 0.31 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.28) | 1 处文件 · `experiments/m1-d1/build_meter.py` |
| `logs/m1-f3b-build` | 1.94 | 74 | 11-18 17:54 | P4 | .dll 0.87／.pdb 0.41／.cs 0.31 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.28) | 1 处文件 · `experiments/m1-f3b/build.py` |
| `logs/m1-n2b-native` | 1.87 | 13 | 11-19 16:44 | P4 | .log 1.80／.jsonl 0.05／.json 0.02 | `engine/game-gvxed22y/stdout.log` (0.66) | — |
| `logs/iih2-rewards` | 1.85 | 43 | 11-20 23:49 | P0 | .log 1.72／.json 0.10／.jsonl 0.03 | `engine/game-l3_kocb3/stdout.log` (0.34) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/m1-f2-teacher-final` | 1.82 | 27 | 11-18 16:10 | P4 | .json 1.21／.log 0.60／.jsonl 0.02 | `game-bu97v8dr/stdout.log` (0.32) | — |
| `logs/iih3-four` | 1.80 | 48 | 11-21 10:24 | P0 | .log 1.75／.jsonl 0.03／.json 0.02 | `engine/game-fh25vvd5/stdout.log` (0.66) | — |
| `logs/iih3-pair16` | 1.76 | 179 | 11-21 10:22 | P0 | .log 1.32／.sqlite 0.35／.jsonl 0.04 | `training.sqlite` (0.35) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/nosl3c-iig-completion-terminal-windows` | 1.75 | 29 | 11-20 21:48 | P4 | .log 1.73／.jsonl 0.02／.json 0.00 | `engine/game-k4lbtx9h/stdout.log` (0.77) | — |
| `logs/iih-e3` | 1.75 | 29 | 11-20 23:10 | P0 | .log 1.73／.jsonl 0.02／.json 0.00 | `engine/game-hqffmt3q/stdout.log` (0.77) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/iih1-e3` | 1.74 | 29 | 11-20 23:23 | P4 | .log 1.72／.jsonl 0.02／.json 0.00 | `engine/game-korwrrgh/stdout.log` (0.77) | — |
| `logs/iih2-e3` | 1.74 | 29 | 11-20 23:49 | P0 | .log 1.72／.jsonl 0.02／.json 0.00 | `engine/game-5t924dtf/stdout.log` (0.77) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/m1-f3a-roots` | 1.74 | 3 | 11-18 16:31 | P4 | .log 1.72／.jsonl 0.02 | `game-p999fqpg/stdout.log` (1.69) | — |
| `logs/nosl3c-iia-qualification` | 1.73 | 106 | 11-20 14:21 | P4 | .log 1.52／.json 0.12／.jsonl 0.09 | `qualification.json` (0.12) | 1 处文件 · `docs/m1-nosl3c-action-coverage.md` |
| `logs/ls2b-export` | 1.70 | 11 | 11-19 21:33 | P4 | .gz 1.58／.json 0.11 | `report-audit.jsonl.gz` (0.85) | — |
| `logs/nosl3c-iic-v2` | 1.69 | 56 | 11-20 16:38 | P4 | .sqlite 0.87／.log 0.75／.json 0.05 | `training.sqlite` (0.87) | — |
| `logs/m0-c3c` | 1.69 | 35 | 11-17 14:27 | P4 | .save 1.21／.il 0.43／.dll 0.03 | `native.il` (0.43) | — |
| `logs/m1-f3a-build` | 1.67 | 70 | 11-18 16:44 | P4 | .dll 0.69／.pdb 0.35／.exe 0.30 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.20) | 1 处文件 · `experiments/m1-f3a/build.py` |
| `logs/m1-f2-build` | 1.65 | 70 | 11-18 16:10 | P4 | .dll 0.68／.pdb 0.35／.exe 0.30 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.20) | 3 处文件 · `experiments/m1-f2/benchmark.py`、`experiments/m1-f2/build.py` |
| `logs/nosl3c-iid-release-resume` | 1.65 | 53 | 11-20 17:07 | P4 | .sqlite 0.87／.log 0.75／.jsonl 0.02 | `training.sqlite` (0.87) | — |
| `logs/nosl3c-iid-rproof` | 1.65 | 53 | 11-20 17:04 | P4 | .sqlite 0.87／.log 0.75／.jsonl 0.02 | `training.sqlite` (0.87) | — |
| `logs/nosl3c-iid-release-control` | 1.65 | 52 | 11-20 17:07 | P4 | .sqlite 0.87／.log 0.75／.jsonl 0.02 | `training.sqlite` (0.87) | — |
| `logs/nosl3c-iid-cproof` | 1.65 | 52 | 11-20 17:04 | P4 | .sqlite 0.87／.log 0.75／.jsonl 0.02 | `training.sqlite` (0.87) | — |
| `logs/m1-n1-audit` | 1.64 | 16 | 11-19 15:07 | P4 | .log 1.51／.json 0.10／.jsonl 0.03 | `engine/game-r6mrav_c/stdout.log` (0.66) | — |
| `logs/nosl3c-iid-resumed` | 1.64 | 53 | 11-20 17:01 | P4 | .sqlite 0.87／.log 0.74／.jsonl 0.02 | `training.sqlite` (0.87) | — |
| `logs/nosl3c-iid-control` | 1.64 | 52 | 11-20 17:01 | P4 | .sqlite 0.87／.log 0.74／.jsonl 0.02 | `training.sqlite` (0.87) | — |
| `logs/nosl3c-iic-rproof` | 1.61 | 54 | 11-20 16:41 | P4 | .sqlite 0.87／.log 0.71／.jsonl 0.02 | `training.sqlite` (0.87) | — |
| `logs/nosl3c-iic-resumed` | 1.61 | 54 | 11-20 16:39 | P4 | .sqlite 0.87／.log 0.71／.jsonl 0.02 | `training.sqlite` (0.87) | — |
| `logs/nosl3c-iic-cproof` | 1.61 | 52 | 11-20 16:41 | P4 | .sqlite 0.87／.log 0.71／.jsonl 0.02 | `training.sqlite` (0.87) | — |
| `logs/nosl3c-iic-control` | 1.61 | 52 | 11-20 16:39 | P4 | .sqlite 0.87／.log 0.71／.jsonl 0.02 | `training.sqlite` (0.87) | — |
| `logs/ls2a-pilot-serial` | 1.61 | 78 | 11-19 20:36 | P4 | .log 1.34／.json 0.14／.sqlite 0.10 | `engine/game-s5ti6kod/stdout.log` (0.32) | — |
| `logs/ls2a-pilot-parallel` | 1.60 | 78 | 11-19 20:36 | P4 | .log 1.34／.json 0.14／.sqlite 0.10 | `engine/game-bcsa_lrg/stdout.log` (0.32) | — |
| `logs/nosl3c-ls2b-regression` | 1.60 | 31 | 11-20 12:02 | P4 | .log 1.52／.jsonl 0.08 | `engine/game-l237t317/stdout.log` (0.33) | — |
| `logs/nosl3a-ls2b-regression` | 1.60 | 31 | 11-19 23:11 | P4 | .log 1.52／.jsonl 0.08 | `engine/game-e63r0hht/stdout.log` (0.33) | — |
| `logs/nosl3b-ls2b-regression` | 1.60 | 31 | 11-20 11:22 | P4 | .log 1.52／.jsonl 0.08 | `engine/game-ly17xd2w/stdout.log` (0.33) | — |
| `logs/nosl3c-ib-ls2b-regression` | 1.60 | 31 | 11-20 13:21 | P4 | .log 1.52／.jsonl 0.08 | `engine/game-nbhq_fnj/stdout.log` (0.33) | — |
| `logs/nosl3c-iig-nested` | 1.59 | 50 | 11-20 18:47 | P4 | .log 1.52／.json 0.04／.jsonl 0.03 | `engine/game-vtdq0q92/stdout.log` (0.28) | — |
| `logs/m1-f1-build` | 1.58 | 68 | 11-18 15:32 | P4 | .dll 0.64／.pdb 0.33／.exe 0.30 | `Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` (0.18) | 2 处文件 · `experiments/m1-f1/benchmark.py`、`experiments/m1-f1/build.py` |
| `logs/iih1-prefix` | 1.58 | 29 | 11-20 23:25 | P4 | .log 1.52／.json 0.04／.jsonl 0.02 | `engine/game-0de2307j/stdout.log` (0.70) | — |
| `logs/m1-ls1-freeze` | 1.55 | 22 | 11-19 19:43 | P4 | .log 1.46／.jsonl 0.05／.json 0.03 | `engine/game-k1tq5aqg/stdout.log` (0.38) | — |
| `logs/nosl3c-iib-native-retained` | 1.53 | 50 | 11-20 16:20 | P4 | .log 1.46／.json 0.04／.jsonl 0.03 | `engine/game-x3wigv12/stdout.log` (0.27) | — |
| `logs/nosl3c-iib-native-extra` | 1.51 | 50 | 11-20 16:19 | P4 | .log 1.46／.jsonl 0.03／.json 0.02 | `engine/game-pq1torq_/stdout.log` (0.27) | — |
| `logs/m1-f2-teacher3` | 1.47 | 27 | 11-18 16:06 | P4 | .json 1.09／.log 0.36／.jsonl 0.01 | `game-3zu2lhly/stdout.log` (0.32) | — |
| `logs/m1-f2-teacher4` | 1.47 | 27 | 11-18 16:06 | P4 | .json 1.09／.log 0.36／.jsonl 0.01 | `game-s_wwlpbf/stdout.log` (0.32) | — |
| `logs/m1-f2-teacher2` | 1.47 | 27 | 11-18 16:04 | P4 | .json 1.09／.log 0.36／.jsonl 0.01 | `game-n_jxpoo6/stdout.log` (0.32) | — |
| `logs/m1-n2a1-pilot` | 1.45 | 37 | 11-19 15:53 | P4 | .json 0.90／.log 0.53／.jsonl 0.02 | `results.json` (0.90) | — |
| `logs/nosl3c-iif-release-diagnostic` | 1.43 | 40 | 11-20 18:24 | P4 | .log 0.86／.sqlite 0.50／.json 0.05 | `training.sqlite` (0.50) | — |
| `logs/nosl3c-iif-release-semantic` | 1.43 | 40 | 11-20 18:23 | P4 | .log 0.86／.sqlite 0.50／.json 0.05 | `training.sqlite` (0.50) | — |
| `logs/nosl3c-iif-train-final` | 1.43 | 40 | 11-20 18:22 | P4 | .log 0.86／.sqlite 0.50／.json 0.05 | `training.sqlite` (0.50) | — |
| `logs/m1-i1-build` | 1.43 | 64 | 11-18 10:35 | P4 | .dll 0.54／.pdb 0.31／.exe 0.30 | `Headless/RunSimulator.cs` (0.17) | 1 处文件 · `experiments/m1-i1/build.py` |
| `logs/nosl3c-iig-completion-frozen` | 1.41 | 145 | 11-20 21:45 | P4 | .log 1.22／.json 0.14／.jsonl 0.04 | `iic/engine/game-h8fb7m6p/stdout.log` (0.13) | — |
| `logs/nosl3c-iif-release-exact` | 1.41 | 40 | 11-20 18:24 | P4 | .log 0.85／.sqlite 0.50／.json 0.03 | `training.sqlite` (0.50) | — |
| `logs/nosl3c-iig-completion-risk-native` | 1.38 | 57 | 11-20 21:46 | P4 | .log 1.30／.json 0.06／.jsonl 0.02 | `engine/game-k0kltjp4/stdout.log` (0.36) | — |
| `logs/ls2a-production-export` | 1.32 | 12 | 11-19 20:54 | P4 | .gz 1.29／.json 0.02 | `manifest.audit.json.gz` (0.42) | — |
| `logs/m1-n2a1-audit-pilot` | 1.19 | 16 | 11-19 15:54 | P4 | .log 1.12／.jsonl 0.04／.json 0.02 | `engine/game-wxccrgb_/stdout.log` (0.33) | — |
| `logs/ls2a-ls1-regression` | 1.12 | 12 | 11-19 20:54 | P4 | .log 0.92／.jsonl 0.20 | `engine/game-h7hppe9p/stdout.log` (0.70) | — |
| `logs/m1-ls1-native-check` | 1.12 | 12 | 11-19 20:03 | P4 | .log 0.92／.jsonl 0.20 | `engine/game-y3_83_rc/stdout.log` (0.70) | — |
| `logs/m1-ls1-native-final` | 1.12 | 12 | 11-19 20:08 | P4 | .log 0.92／.jsonl 0.20 | `engine/game-nbtnflln/stdout.log` (0.70) | — |
| `logs/m1-f1-before` | 1.10 | 6 | 11-17 16:33 | P4 | .log 1.09／.jsonl 0.01 | `game-vpyf2owp/stdout.log` (0.90) | — |
| `logs/ls2b-pilot` | 1.08 | 18 | 11-19 21:27 | P4 | .log 0.87／.json 0.14／.sqlite 0.05 | `engine/game-n3k4wb6d/stdout.log` (0.67) | — |
| `logs/nosl3c-iib-resume-final` | 1.04 | 21 | 11-20 16:23 | P4 | .sqlite 0.87／.log 0.16／.jsonl 0.01 | `training.sqlite` (0.87) | — |
| `logs/nosl3c-iib-control-final` | 1.04 | 19 | 11-20 16:23 | P4 | .sqlite 0.87／.log 0.16／.jsonl 0.01 | `training.sqlite` (0.87) | — |
| `logs/nosl3c-iib-control` | 1.04 | 19 | 11-20 14:50 | P4 | .sqlite 0.87／.log 0.16／.jsonl 0.01 | `training.sqlite` (0.87) | — |
| `logs/nosl3c-iib-resume` | 1.04 | 19 | 11-20 14:50 | P4 | .sqlite 0.87／.log 0.16／.jsonl 0.01 | `training.sqlite` (0.87) | — |
| `logs/m1-f2-pilot` | 1.04 | 27 | 11-18 16:02 | P4 | .json 0.96／.log 0.08／.jsonl 0.00 | `ironclad-a0-run_1-archive-175.save.json` (0.07) | — |
| `logs/m1-n1-public` | 1.03 | 25 | 11-19 15:07 | P4 | .log 0.83／.json 0.20／.jsonl 0.01 | `public-target.json` (0.20) | — |
| `logs/m1-d1-extend` | 1.02 | 24 | 11-18 18:38 | P4 | .json 0.62／.log 0.39／.jsonl 0.00 | `manifest.json` (0.26) | — |
| `logs/m0-c3` | 0.99 | 21 | 11-17 14:04 | P4 | .save 0.54／.il 0.28／.json 0.14 | `native-heal.il` (0.11) | — |
| `logs/m1-n1-experiment` | 0.97 | 97 | 11-19 15:07 | P4 | .log 0.92／.gz 0.03／.jsonl 0.02 | `engine/game-j0tw7g5t/stdout.log` (0.07) | — |
| `logs/nosl3c-iib-native-final` | 0.96 | 50 | 11-20 16:17 | P4 | .log 0.92／.jsonl 0.02／.json 0.02 | `engine/game-cxew1ejb/stdout.log` (0.16) | — |
| `logs/m0-c2b` | 0.95 | 54 | 11-17 13:53 | P4 | .save 0.76／.dll 0.07／.pdb 0.06 | `closeout-saves/merchant-route0/S.save` (0.05) | — |
| `logs/nosl3c-iie-choice` | 0.94 | 29 | 11-20 17:27 | P4 | .sqlite 0.50／.log 0.42／.jsonl 0.01 | `training.sqlite` (0.50) | — |
| `logs/m1-d2b-probe` | 0.87 | 21 | 11-18 19:05 | P4 | .log 0.74／.json 0.12／.jsonl 0.01 | `iron-6-a2/game-u3s80s4n/stdout.log` (0.26) | — |
| `logs/m1-n2f-a2-repro` | 0.83 | 3 | 11-19 19:21 | P4 | .gz 0.54／.json 0.29 | `weights.json.gz` (0.54) | 1 处文件 · `docs/m1-n2f-a2-offline-learning-pilot.md` |
| `logs/iih1-prefix-final` | 0.79 | 8 | 11-20 23:26 | P4 | .log 0.77／.json 0.01／.jsonl 0.01 | `engine/game-gvyiw8y2/stdout.log` (0.65) | — |
| `logs/m0v4-20261117-123411` | 0.78 | 8 | 11-17 12:34 | P4 | .dll 0.71／.jsonl 0.04／.log 0.04 | `windows-deps/Vortice.DirectX.dll` (0.26) | — |
| `logs/m0-c2` | 0.77 | 15 | 11-17 13:45 | P4 | .txt 0.27／.json 0.26／.save 0.16 | `report.json` (0.13) | — |
| `logs/m1-n2a-pilot2` | 0.76 | 37 | 11-19 15:27 | P4 | .json 0.40／.log 0.34／.jsonl 0.02 | `results.json` (0.40) | — |
| `logs/nosl3c-iig-completion-current` | 0.76 | 101 | 11-20 21:47 | P4 | .log 0.73／.jsonl 0.02／.json 0.01 | `engine/game-idvgzb0e/stdout.log` (0.12) | — |
| `logs/m1-f3b-sentinel-pilot` | 0.75 | 13 | 11-18 17:56 | P4 | .log 0.68／.json 0.05／.jsonl 0.02 | `sentinel/game-sct_0_2x/stdout.log` (0.35) | — |
| `logs/nosl3c-iib-native-v3` | 0.72 | 29 | 11-20 14:50 | P4 | .log 0.70／.jsonl 0.02／.json 0.01 | `engine/game-k4wk_ikq/stdout.log` (0.16) | — |
| `logs/nosl3c-iif-direct-final` | 0.71 | 73 | 11-20 18:22 | P4 | .log 0.61／.jsonl 0.07／.json 0.03 | `engine/game-8ae232k2/stdout.log` (0.09) | — |
| `logs/m1-f1-study` | 0.70 | 7 | 11-18 15:27 | P4 | .log 0.49／.json 0.20／.jsonl 0.01 | `game-el3b2j2_/stdout.log` (0.48) | — |
| `logs/m1-n1-complete` | 0.69 | 6 | 11-19 15:05 | P4 | .gz 0.69／.jsonl 0.00 | `results.jsonl.gz` (0.69) | — |
| `logs/nosl3c-iif-direct-broad` | 0.69 | 65 | 11-20 18:23 | P4 | .log 0.59／.jsonl 0.07／.json 0.03 | `engine/game-ge1cm1az/stdout.log` (0.16) | — |
| `logs/nosl3c-iia-roots` | 0.63 | 53 | 11-20 14:18 | P4 | .log 0.59／.jsonl 0.02／.json 0.02 | `engine/game-7ej31e2p/stdout.log` (0.04) | 1 处文件 · `docs/m1-nosl3c-action-coverage.md` |
| `logs/m0-c3b` | 0.63 | 24 | 11-17 14:18 | P4 | .save 0.57／.json 0.02／.dll 0.02 | `after-random-B.save` (0.07) | — |
| `logs/nosl3c-iig-completion-recovery-cases` | 0.61 | 39 | 11-20 21:32 | P4 | .log 0.54／.json 0.06／.jsonl 0.01 | `engine/game-bobacff7/stdout.log` (0.19) | — |
| `logs/m1-f3b-pilot` | 0.61 | 35 | 11-18 17:51 | P4 | .json 0.37／.log 0.23／.jsonl 0.00 | `offering-east-052.save.json` (0.08) | — |
| `logs/nosl3c-iig-completion-original` | 0.60 | 46 | 11-20 21:46 | P4 | .log 0.54／.jsonl 0.04／.json 0.03 | `engine/game-wqf1wmmt/stdout.log` (0.14) | — |
| `logs/m0-v5b` | 0.60 | 25 | 11-17 13:07 | P4 | .log 0.30／.save 0.25／.jsonl 0.04 | `smoke/host.log` (0.24) | — |
| `logs/nosl3c-iib-training` | 0.60 | 11 | 11-20 14:44 | P4 | .sqlite 0.50／.log 0.09／.jsonl 0.00 | `training.sqlite` (0.50) | — |
| `logs/nosl3c-iig-completion-draw-instances` | 0.55 | 36 | 11-20 21:57 | P4 | .log 0.53／.jsonl 0.01／.json 0.01 | `engine/game-cigcbjzv/stdout.log` (0.17) | — |
| `logs/nosl3b-tests` | 0.53 | 52 | 11-20 21:44 | P4 | .log 0.51／.jsonl 0.02 | `engine/game-c8p1x5h1/stdout.log` (0.04) | 1 处文件 · `experiments/m1-nosl3b/test_nosl3b.py` |
| `logs/nosl3c-iig-completion-original-risk` | 0.52 | 65 | 11-20 21:52 | P4 | .log 0.43／.json 0.04／.jsonl 0.04 | `engine/game-rkjqwrvp/stdout.log` (0.06) | — |
| `logs/iih-risk` | 0.52 | 65 | 11-20 23:11 | P0 | .log 0.43／.json 0.04／.jsonl 0.04 | `engine/game-at0u10h8/stdout.log` (0.06) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/nosl3c-iig-certified-reveal` | 0.49 | 49 | 11-20 18:56 | P4 | .log 0.47／.jsonl 0.01／.json 0.01 | `engine/game-wdou8kzm/stdout.log` (0.12) | — |
| `logs/iih3-archive` | 0.48 | 61 | 11-21 10:21 | P0 | .log 0.45／.jsonl 0.02／.txt 0.01 | `engine/game-lf_si7px/stdout.log` (0.07) | 1 处文件 · `docs/m1-nosl3c-solver-semantic-convergence.md` |
| `logs/iih3-target` | 0.44 | 13 | 11-21 10:23 | P0 | .log 0.42／.json 0.01／.jsonl 0.01 | `engine/game-zoaug_b9/stdout.log` (0.30) | — |
| `logs/nosl3c-iib-native` | 0.37 | 22 | 11-20 14:47 | P4 | .log 0.36／.jsonl 0.01／.json 0.00 | `engine/game-r4n17zjr/stdout.log` (0.12) | — |
| `logs/nosl3c-iid-iia` | 0.36 | 15 | 11-20 17:02 | P4 | .log 0.23／.json 0.12／.jsonl 0.01 | `qualification.json` (0.12) | — |
| `logs/nosl3c-iie-iia` | 0.36 | 15 | 11-20 17:26 | P4 | .log 0.23／.json 0.12／.jsonl 0.01 | `qualification.json` (0.12) | — |
| `logs/nosl3c-iic-iia` | 0.36 | 15 | 11-20 16:40 | P4 | .log 0.23／.json 0.12／.jsonl 0.01 | `qualification.json` (0.12) | — |
| `logs/nosl3c-iif-iia` | 0.36 | 15 | 11-20 18:23 | P4 | .log 0.23／.json 0.12／.jsonl 0.01 | `qualification.json` (0.12) | — |
| `logs/nosl3c-iig-iia` | 0.36 | 15 | 11-20 18:43 | P4 | .log 0.23／.json 0.12／.jsonl 0.01 | `qualification.json` (0.12) | — |
| `logs/m1-n2a-measured-native` | 0.36 | 13 | 11-19 15:31 | P4 | .log 0.35／.json 0.01／.jsonl 0.01 | `engine/game-9n2krf3s/stdout.log` (0.10) | — |
| `logs/m1-n2a-native` | 0.36 | 13 | 11-19 15:29 | P4 | .log 0.35／.json 0.01／.jsonl 0.01 | `engine/game-kq0fuipg/stdout.log` (0.10) | — |
| `logs/m1-d1-quarantine` | 0.32 | 4 | 11-18 18:32 | P4 | .json 0.32／(none) 0.00 | `manifest.json` (0.22) | — |
| `logs/m1-f2-seeds` | 0.31 | 123 | 11-17 16:51 | P4 | .log 0.31／.jsonl 0.00 | `game-exunek2j/stdout.log` (0.00) | — |
| `logs/m1-n1-baseline` | 0.31 | 12 | 11-19 14:55 | P4 | .log 0.29／.gz 0.02／.jsonl 0.00 | `engine/game-vahb6xhf/stdout.log` (0.17) | — |
| `logs/m1-d1-shop-choice` | 0.30 | 3 | 11-18 18:41 | P4 | .log 0.29／.jsonl 0.00 | `engine/game-gbalosp7/stdout.log` (0.28) | — |
| `logs/nosl3c-iif-direct` | 0.29 | 25 | 11-20 18:19 | P4 | .log 0.24／.jsonl 0.04／.json 0.01 | `engine/game-ma9lvtp8/stdout.log` (0.07) | — |
| `logs/nosl3c-iig-completion-draw-cases` | 0.28 | 28 | 11-20 21:27 | P4 | .log 0.21／.json 0.06／.jsonl 0.01 | `engine/game-8pgq8blj/stdout.log` (0.04) | — |
| `logs/nosl3c-iig-certified-native` | 0.27 | 52 | 11-20 18:58 | P4 | .log 0.26／.jsonl 0.01／.json 0.00 | `engine/game-eq8dmol6/stdout.log` (0.02) | — |
| `logs/iih3-old` | 0.27 | 20 | 11-21 10:25 | P0 | .log 0.25／.json 0.01／.jsonl 0.01 | `engine/game-9jmxoeqr/stdout.log` (0.11) | — |
| `logs/nosl3c-iig-reveal-verified` | 0.26 | 29 | 11-20 18:46 | P4 | .log 0.24／.jsonl 0.01／.json 0.00 | `engine/game-4wyqm3ip/stdout.log` (0.06) | — |
| `logs/nosl3c-iib-extra` | 0.23 | 21 | 11-20 14:52 | P4 | .log 0.22／.jsonl 0.01 | `engine/game-y1mw9fyb/stdout.log` (0.11) | — |
| `logs/nosl3c-iig-guarded-reveal` | 0.23 | 31 | 11-20 18:51 | P4 | .log 0.22／.jsonl 0.01／.json 0.00 | `engine/game-vbo2rcxo/stdout.log` (0.04) | — |
| `logs/nosl3c-iia-costs` | 0.22 | 36 | 11-20 14:18 | P4 | .log 0.21／.jsonl 0.01／.json 0.00 | `engine/game-9n8dip4g/stdout.log` (0.03) | 1 处文件 · `docs/m1-nosl3c-action-coverage.md` |
| `logs/m1-f3a-first-discovery` | 0.21 | 3 | 11-18 16:34 | P4 | .json 0.21 | `manifest.json` (0.18) | — |
| `logs/nosl3c-iie-old-death` | 0.19 | 8 | 11-20 17:25 | P4 | .log 0.17／.json 0.01／.jsonl 0.00 | `engine/game-1m6jk8uz/stdout.log` (0.13) | — |
| `logs/nosl3c-iic-death` | 0.19 | 8 | 11-20 16:38 | P4 | .log 0.17／.json 0.01／.jsonl 0.00 | `engine/game-_gcnae4e/stdout.log` (0.13) | — |
| `logs/nosl3c-iid-iic` | 0.19 | 8 | 11-20 17:02 | P4 | .log 0.17／.json 0.01／.jsonl 0.00 | `engine/game-uogu_4ko/stdout.log` (0.13) | — |
| `logs/nosl3c-iif-iic` | 0.19 | 8 | 11-20 18:25 | P4 | .log 0.17／.json 0.01／.jsonl 0.00 | `engine/game-enttn7l6/stdout.log` (0.13) | — |
| `logs/nosl3c-iig-iic` | 0.19 | 8 | 11-20 18:44 | P4 | .log 0.17／.json 0.01／.jsonl 0.00 | `engine/game-_mz26tsc/stdout.log` (0.13) | — |
| `logs/nosl3c-iid-public` | 0.19 | 37 | 11-20 17:03 | P4 | .log 0.18／.jsonl 0.01／.json 0.00 | `engine/game-5nr5j4x3/stdout.log` (0.02) | — |
| `logs/nosl3c-iid-release-public` | 0.19 | 37 | 11-20 17:07 | P4 | .log 0.18／.jsonl 0.01／.json 0.00 | `engine/game-k03yu9gk/stdout.log` (0.02) | — |
| `logs/nosl3c-iie-iib` | 0.18 | 37 | 11-20 17:27 | P4 | .log 0.18／.jsonl 0.01／.json 0.00 | `engine/game-84rhdqyy/stdout.log` (0.02) | — |
| `logs/nosl3c-iid-iib` | 0.18 | 37 | 11-20 17:02 | P4 | .log 0.18／.jsonl 0.01／.json 0.00 | `engine/game-ak2jv5t1/stdout.log` (0.02) | — |
| `logs/nosl3c-iif-iib` | 0.18 | 37 | 11-20 18:23 | P4 | .log 0.18／.jsonl 0.01／.json 0.00 | `engine/game-u8ch58u1/stdout.log` (0.02) | — |
| `logs/nosl3c-iic-iib` | 0.18 | 37 | 11-20 16:40 | P4 | .log 0.18／.jsonl 0.01／.json 0.00 | `engine/game-9fvoixgy/stdout.log` (0.02) | — |
| `logs/nosl3c-iib-equivalence` | 0.18 | 37 | 11-20 14:51 | P4 | .log 0.18／.jsonl 0.01／.json 0.00 | `engine/game-inmajn5p/stdout.log` (0.02) | — |
| `logs/nosl3c-iig-iib` | 0.18 | 37 | 11-20 18:43 | P4 | .log 0.18／.jsonl 0.01／.json 0.00 | `engine/game-6fj6r5j8/stdout.log` (0.02) | — |
| `logs/m1-ls1-cli-report-check` | 0.18 | 5 | 11-19 20:11 | P4 | .log 0.15／.jsonl 0.02／.json 0.01 | `engine/game-fagf8xh9/stdout.log` (0.14) | — |
| `logs/m0-a2` | 0.17 | 9 | 11-17 12:50 | P4 | .save 0.15／.log 0.02／.xml 0.00 | `final-saves/m0a20/S1.save` (0.05) | — |
| `logs/m1-n2a1-duplicate-final` | 0.17 | 11 | 11-19 16:00 | P4 | .log 0.12／.json 0.04／.jsonl 0.01 | `duplicate.json` (0.04) | — |
| `logs/m1-n2a1-duplicate` | 0.17 | 11 | 11-19 15:59 | P4 | .log 0.12／.json 0.04／.jsonl 0.01 | `duplicate.json` (0.04) | — |
| `logs/m1-b1-dotnet` | 0.16 | 1 | 10-29 20:23 | P4 | .exe 0.16 | `dotnet.exe` (0.16) | — |
| `logs/m1-ls1-cli-check` | 0.16 | 5 | 11-19 20:09 | P4 | .log 0.12／.jsonl 0.03／.json 0.01 | `engine/game-ogd_mxme/stdout.log` (0.12) | — |
| `logs/m1-f2-prepared` | 0.15 | 13 | 11-18 16:07 | P4 | .log 0.14／.json 0.01／.jsonl 0.00 | `game-5o0rem1_/stdout.log` (0.03) | — |
| `logs/nosl3c-iic` | 0.14 | 2 | 11-20 16:36 | P4 | .sqlite 0.14／(none) 0.00 | `training.sqlite` (0.14) | — |
| `logs/nosl3c-iig-completion-capture` | 0.13 | 15 | 11-20 21:22 | P4 | .log 0.10／.json 0.02／.jsonl 0.00 | `engine/game-k804g5gx/stdout.log` (0.04) | — |
| `logs/nosl3c-iid-allies` | 0.12 | 22 | 11-20 17:04 | P4 | .log 0.12／.jsonl 0.00／.json 0.00 | `engine/game-5mafcah2/stdout.log` (0.02) | — |
| `logs/nosl3c-iig-reveal-diff` | 0.11 | 7 | 11-20 18:47 | P4 | .log 0.11／.jsonl 0.00 | `engine/game-9lblkure/stdout.log` (0.06) | — |
| `logs/nosl3c-iig-reveal-release` | 0.11 | 14 | 11-20 18:43 | P4 | .log 0.11／.jsonl 0.00 | `engine/game-hn4tc3uy/stdout.log` (0.03) | — |
| `logs/nosl3c-iig-reveal-final` | 0.11 | 12 | 11-20 18:45 | P4 | .log 0.10／.jsonl 0.00／.json 0.00 | `engine/game-y6kwwdsc/stdout.log` (0.04) | — |
| `logs/nosl3c-iie-release-death` | 0.11 | 20 | 11-20 17:25 | P4 | .log 0.10／.json 0.00／.jsonl 0.00 | `engine/game-1ox8i6ah/stdout.log` (0.03) | — |
| `logs/nosl3c-iig-iie` | 0.11 | 20 | 11-20 18:44 | P4 | .log 0.10／.json 0.00／.jsonl 0.00 | `engine/game-mlrp1tni/stdout.log` (0.03) | — |
| `logs/nosl3c-iie-death` | 0.11 | 20 | 11-20 17:22 | P4 | .log 0.10／.json 0.00／.jsonl 0.00 | `engine/game-7w7t4db3/stdout.log` (0.03) | — |
| `logs/nosl3c-iif-iie` | 0.11 | 20 | 11-20 18:23 | P4 | .log 0.10／.json 0.00／.jsonl 0.00 | `engine/game-0oab0uzz/stdout.log` (0.03) | — |
| `logs/m1-n2a1-formal` | 0.10 | 11 | 11-19 15:56 | P4 | .log 0.10／.jsonl 0.00 | `engine/game-90ss8yed/stdout.log` (0.04) | — |
| `logs/nosl-iib-probe` | 0.09 | 19 | 11-20 14:43 | P4 | .log 0.08／.jsonl 0.00 | `engine/game-qzgidnzo/stdout.log` (0.02) | — |
| `logs/nosl3c-iig-dynamic` | 0.08 | 15 | 11-20 18:47 | P4 | .log 0.07／.jsonl 0.00／.json 0.00 | `engine/game-np4troan/stdout.log` (0.02) | — |
| `logs/nosl3c-iid-team` | 0.08 | 15 | 11-20 17:06 | P4 | .log 0.07／.jsonl 0.00／.json 0.00 | `engine/game-6jvqr70_/stdout.log` (0.02) | — |
| `logs/nosl3c-iif-iid` | 0.08 | 15 | 11-20 18:25 | P4 | .log 0.07／.jsonl 0.00／.json 0.00 | `engine/game-jrkixieu/stdout.log` (0.02) | — |
| `logs/nosl3c-iie-iid` | 0.08 | 15 | 11-20 17:27 | P4 | .log 0.07／.jsonl 0.00／.json 0.00 | `engine/game-ezun3i_a/stdout.log` (0.02) | — |
| `logs/nosl3c-iig-iid` | 0.08 | 15 | 11-20 18:44 | P4 | .log 0.07／.jsonl 0.00／.json 0.00 | `engine/game-yft8uyrh/stdout.log` (0.02) | — |
| `logs/m0-c1` | 0.06 | 2 | 11-17 13:24 | P4 | .json 0.04／.txt 0.02 | `results.json` (0.04) | — |
| `logs/nosl3c-iig-reveal` | 0.06 | 7 | 11-20 18:39 | P4 | .log 0.06／.jsonl 0.00 | `engine/game-8dlvru6f/stdout.log` (0.03) | — |
| `logs/m1-n2a-mechanics2` | 0.05 | 8 | 11-19 15:32 | P4 | .log 0.04／.json 0.01／.jsonl 0.00 | `engine/game-otwtzjfv/stdout.log` (0.02) | — |
| `logs/m1-n2a-mechanics-final` | 0.05 | 8 | 11-19 15:33 | P4 | .log 0.04／.json 0.01／.jsonl 0.00 | `engine/game-0_zj1qq_/stdout.log` (0.02) | — |
| `logs/m1-n2a1-mechanics-final` | 0.05 | 8 | 11-19 16:00 | P4 | .log 0.04／.json 0.01／.jsonl 0.00 | `engine/game-551lgzf7/stdout.log` (0.02) | — |
| `logs/ls2a-kaiser-diagnostic` | 0.04 | 8 | 11-19 20:47 | P4 | .log 0.02／.json 0.02／.jsonl 0.00 | `8629b8c80ddc51a9e78a.json` (0.01) | — |
| `logs/ls2a-qualified-export` | 0.03 | 4 | 11-19 20:42 | P4 | .gz 0.02／.json 0.01 | `summary.json` (0.01) | — |
| `logs/iih3-current` | 0.03 | 7 | 11-21 10:29 | P0 | .log 0.02／.jsonl 0.00／.txt 0.00 | `engine/game-j34xx1uc/stdout.log` (0.02) | — |
| `logs/iih3-draw` | 0.03 | 13 | 11-21 10:30 | P0 | .log 0.02／.jsonl 0.00／.txt 0.00 | `engine/game-0j72lbz_/stdout.log` (0.02) | — |
| `logs/m1-l2-native` | 0.02 | 7 | 11-18 11:11 | P4 | .log 0.02／.txt 0.00／.jsonl 0.00 | `game-ukz5m4_h/stdout.log` (0.01) | — |
| `logs/m1-d1-main` | 0.02 | 3 | 11-18 18:17 | P4 | .json 0.02／(none) 0.00 | `manifest.json` (0.01) | — |
| `logs/m1-review-five-characters` | 0.01 | 55 | 11-17 15:19 | P4 | .log 0.00／.json 0.00 | `Regent.json` (0.00) | — |
| `logs/m1-f1-runs` | 0.01 | 55 | 11-17 16:35 | P4 | .log 0.00／.json 0.00 | `Defect.json` (0.00) | — |
| `logs/m1-n2a-mechanics` | 0.00 | 3 | 11-19 15:31 | P4 | .log 0.00／.jsonl 0.00 | `engine/game-p3cxipft/stderr.log` (0.00) | — |
| `logs/m1-b1-full-runs` | 0.00 | 50 | 11-17 15:04 | P4 | .log 0.00 | `Regent-4/stdout.log` (0.00) | — |
| `logs/nosl3c-iig-completion-native-regression` | 0.00 | 5 | 11-20 22:02 | P4 | .json 0.00 | `Defect/results.json` (0.00) | — |
| `logs/nosl3c-iig-completion-native-batch` | 0.00 | 5 | 11-20 21:59 | P4 | .json 0.00 | `Defect/results.json` (0.00) | — |
| `logs/dotnet-home` | 0.00 | 10 | 11-17 19:45 | P1 | .json 0.00／.dotnetuserlevelcache 0.00／.txt 0.00 | `.dotnet/sdk-advertising/10.0.400/microsoft.net.workloads/10.0.404/microsoft.net.workloads.workloadset.json` (0.00) | 16 处文件 · `docs/m1-cs1-combat-performance.md`、`docs/m1-nosl3c-interaction-completion.md` |
| `logs/m1-ls1-test-tools` | 0.00 | 1 | 11-19 20:08 | P4 | .cmd 0.00 | `dotnet.cmd` (0.00) | — |

</details>
