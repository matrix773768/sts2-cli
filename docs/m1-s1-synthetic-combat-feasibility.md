# M1-S1 原生合成战斗可行性实验

2026-11-18。基线 `0512f270866c4b693a6661266fef290d73e13997`，Windows x64，STS2 v0.113.1 / Build 26660232，CoreCLR 9.0.7，冻结 CombatSolver 0.51.5。

**在没有合法地图历史的条件下，3 个合成配置全部通过两次独立原生重建。** 在基础根上，冻结 F3B C 用 128 次额度中的 **13 次预测转移**找到无药胜路，另起原生进程重建后严格验收 **13/13 步**，最后到达 `card_reward`。

[配置示例](../experiments/m1-s1/cases.json) · [SyntheticCombatSpec Schema](../experiments/m1-s1/spec.schema.json) · [结构化实测结果](../experiments/m1-s1/results.json)

## 原生入口与参考项目的关系

- STS2Dojo 的临时跑局先用原生 `RunState.CreateForNewRun` 和 `SetUpNewSingleplayer(... shouldSave:false)` 建立运行上下文，再直接进入指定遭遇。它避免在遭遇对象上触发基于时间的 RNG 重新随机化，并采用固定解锁范围。其界面、场景加载和跨幕适配超出本次范围。 [DojoLaunch.cs](https://github.com/carlineng/STS2Dojo/blob/main/STS2DojoCode/DojoLaunch.cs) · [DojoConsoleCmd.cs](https://github.com/carlineng/STS2Dojo/blob/main/STS2DojoCode/DojoConsoleCmd.cs)
- Dojo 的共享快照在进场前记录种子、原生跑局及玩家 RNG、身份和可序列化资源。S1 采用配置加确定性冷启动，并在战斗开局读取 RNG 的计数和全部状态字。当前入口从 seed 初始化，无需导入或覆盖 RNG 计数。 [SeedSharing/DojoFightSnapshot.cs](https://github.com/carlineng/STS2Dojo/blob/main/STS2DojoCode/SeedSharing/DojoFightSnapshot.cs)
- 仓库现有 `start_run` 会进入第一幕地图并触发涅奥流程。`set_player` 的部分资源处理依赖内部字段。S1 复用 headless 原生玩家创建、选择器、事件泵及动作入口，在隔离宿主增加 `synthetic_start`、`synthetic_snapshot`。由真实 `RunState` 初始化卡牌所有权和顺序，调用原生升级、HP、遗物和药水操作，再把可变原生 `EncounterModel` 交给 `EnterRoomDebug`。场景为第 0 层，没有访问地图节点。
- 宿主禁止地图和存档命令，每个进程只初始化一次合成战斗，并关闭游戏存档和战斗回放写入。运行目录及 profile 由已有 EngineClient 独立分配。本批 9 个冷进程中检查到 0 个原生存档或战斗回放文件。定向测试另确认保存、加载、带存档路径退出、地图查询及同进程二次启动均拒绝，且活状态摘要保持。

## 数据与重建合同

`SyntheticCombatSpec` v1 保存角色、Ascension、遭遇 ID、seed、有序卡组和升级、HP / Max HP、遗物和药水槽。每个结果根保存完整配置、原生版本、原生 DLL 和隔离宿主哈希、公开开局、原生资源、有序手牌、抽牌堆、弃牌堆及消耗牌堆、12 个跑局 RNG 流和 4 个玩家流，以及整个原生 continuation 内容和 SHA-256。同配置的两次冷启动比较完整根，而后才设置 `native_verified=true`。

本批所有样本均为 `synthetic=true`、`native_reachable=false`。独立重建通过后为 L0，附独立严格原生胜路的基础根为 L3。合成 ID 以 `synthetic-` 开头，包含规范化配置、版本和 live 身份。后续数据工厂可复用 `rebuild(output, root)` 作为单独的来源适配器，继续保留真实地图来源的审计合同。S1 数据独立输出，D1 的清单和历史保持原样。

| 用例 | 配置与结果 | 原生 live 摘要前缀 |
| --- | --- | --- |
| A / B | 铁甲战士 A0，`SHRINKER_BEETLE_WEAK`，`S1TEST01`，5 打击、4 防御、1 痛击，60/80 HP，燃烧之血，槽位 1 肌肉药水（从 0 开始）。两个冷进程完全相等，两次各执行相同的前三条合法 Q1 动作，状态及 RNG 摘要逐步相等。 | `87c07d2714273b2f` |
| C | 只改为 `S1TEST02`。两次冷重建相等，原生跑局及玩家随机流的状态字与 A/B 分别不同。 | `e5445a928609e9ca` |
| D | 保持 `S1TEST01`，只将原生牌组末张痛击升级一级。两次冷重建相等，原生牌组恰好一张改变。 | `f65e5aca3b652ffb` |

## F3B 与实测开销

冻结 F3B 搜索和固定帧准备接受 S1 的重建入口。搜索前后核对源原生摘要；下一进程以同配置重建并固定重算预测帧，逐步摘要与搜索结果一致；最后再开一个进程重建并调用 F3A 严格重放。十三步预测帧与原生帧、终局回调位置全部一致。入场 60 HP，累计掉血 10，锁定 50 HP，经燃烧之血结算到 56 HP，敌人 HP 为 0，药水未消耗。预测搜索使用内部 RNG。

| 区间 | 墙钟 | 引擎峰值工作集 |
| --- | ---: | ---: |
| 6 次冷初始化核对 | P50 1.97 秒，范围 1.83–2.03 秒 | 99.1 MiB |
| F3B 搜索含冷重建 | 3.15 秒，搜索热段 0.46 秒 | 113.7 MiB |
| 固定预测帧含冷重建 | 3.10 秒 | 114.3 MiB |
| 独立原生胜路验收含冷重建 | 2.38 秒 | 104.0 MiB |
| 整个实验 | 21.02 秒 | 进程串行 |

冷启动的握手、原生初始化和开局快照 P50 分别为 0.226、1.580、0.150 秒。测试控制组额外实测 85 Max HP 与空遗物配置。开发中先确认原生入场，再修正独立快照的求解器加载和 RNG DTO 字段序列化。三次隔离 SDK 构建用时 9.08、8.22、8.41 秒，均 0 错误、7 条既有警告。S1 三项及 D2B 九项回归全部通过，合计 12.51 秒。三个完整 Spec 均通过 Schema；Python 编译和 Git diff 检查通过。本次未执行全量 pytest 或五角色批次。

支持范围为默认第一幕普通原生遭遇，遗物限燃烧之血，药水限肌肉药水及空槽，升级级别限 0/1。正式实测仅覆盖铁甲战士 A0 的一个遭遇。其他角色、Ascension、跨幕、特殊遭遇和复杂遗物钩子仍需独立验证。本实验的药水路径验证了合法槽位采购和重建，胜路采用无主动药水。扩到中后期前需另验证对应幕和变体的原生初始化。

## 复现

使用 [项目环境](PROJECT_STATUS.md) 中的本地原生 DLL、冻结 CombatSolver、CoreCLR 9.0.7 和 pytest。

```powershell
python -X utf8 experiments/m1-s1/build.py
python -X utf8 experiments/m1-s1/run.py logs/m1-s1/repro
$env:STS2_S1_RESULTS = (Resolve-Path logs/m1-s1/repro).Path
python -X utf8 -m pytest experiments/m1-s1/test_synthetic.py -q
```

`run.py` 也接受 `--cases`，用来提供 `base`、`seed`、`upgrade` 三个完整 Spec。输出目录必须为新路径。`results.json` 包含完整可重建根，`f3b-private.json.gz` 在本地保存搜索过程，仓库版本化的是配置和实测摘要。
