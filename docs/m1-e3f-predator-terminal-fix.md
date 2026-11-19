# M1-E3F 猎杀者终局预测镜像修复

基线为 `3b3fd97`，分支 `port/v0.113.1`，起始工作区干净。使用原生 v0.113.1／Steam Build 26660232、CoreCLR 9.0.7、SDK 10.0.404。修复版基于 CombatSolver 0.51.5 的固定源码 `78e4545e825e58c3d999354b1ffcd54241b1d2cf`，隔离 Release 版本为 **0.51.5-e3f.1**。

**修复版在两条 E3 猎杀者最短失败前缀上与独立原生逐帧完全相等。** 非致死、跨回合消费及击杀一名主要敌人但仍有其他主要敌人的对照也通过。原生敌方侧终局的计数差分仍然存在，比较器没有豁免。

## 修复位置

原生 `Predator.OnPlay` 等待攻击完成，接着尝试施加延迟抽牌。原生 `PowerCmd.Apply` 首先检查 `CombatManager.IsEnding`。冻结预测的通用 post-OnPlay 规则提前执行登记的 Power，此时预测卡牌结算尚未完成死亡清扫。

[补丁](../experiments/m1-e3f/predator.patch) 保留镜像覆盖登记用于原有完整性检查，仅把猎杀者的延迟抽牌实际应用推迟到既有 `ApplyEnemyDeathPowers` 成功之后、卡牌后续结算之前。此处调用预测器现成的 `IsEnding`，它检查待决失败、存活主要敌人、尚未结算的生成型死亡，以及 `ShouldStopCombatFromEnding`。战斗仍继续时应用同一 Power 2。普通 Power 登记和其它卡牌的后置处理照常执行。死亡清扫如果遇到需要挂起的选择，猎杀者路径显式报告 unsupported，避免产出缺失后置效果的完整结果。

开发中，直接删除猎杀者登记虽然通过固定前缀，却触发 F3B 的 `MethodMirrorIncomplete` 风险并使首个猎杀者根耗尽。最终补丁保留覆盖登记，在原位置只跳过该 Power 的实际应用，搜索回归以最终构建为准。

## 独立原生证据

每个病例使用两个独立预测进程，以及另一个仅执行原生动作的冷进程。通过宿主读取实际加载的程序集属性与文件 SHA-256。比对每步完整预测和原生帧，包括 Power、HP、最大 HP、药水槽、金币、牌堆、升级及续体内的 RNG。原版和原生重新运行的全部帧也与 E3 历史证据一致。比较止于战斗边界，奖励生成和跨房成长未做通用验证。

| 开发对照 | 观测 | 修复版严格帧差分 |
| --- | --- | --- |
| `660d09b2…` 非致死与跨回合 | 第 1 步敌人剩 29 HP，两端均获得 Power 2；第 5 步跨回合正常消耗 | 0 |
| 同根最后一击 | 第 7 步胜利，两端均无该 Power，终局 28 HP、药水槽空 | 0 |
| `44ffda5a…` 持药最后一击 | 第 16 步胜利，两端均无该 Power，终局 59 HP、第三槽为 Flex Potion | 0 |
| 同持药根更换首回合顺序 | 两次 Backstab、Strike、Predator；第一名敌人 0 HP，另一名 36 HP，仍处于活动战斗，两端均获得 Power 2 | 0 |
| `a85bf9f7…` 敌方侧终局 | 第 15 步仍存在 `Y` 和 `AttackStarts` 差分 | 2，与冻结版相同 |

未构造带 `ShouldStopCombatFromEnding` 的原生猎杀者实机夹具，也未注入死亡清扫挂起选择。补丁复用现有 hook 判定，该机制及模组替代 OnPlay 仍待专项验证。

## 配对首胜与胜后回归

四个开发根都运行原封不动的 F3B C 和固定 F4，禁主动药水、共享 512 次转移。两个猎杀者根的首胜动作、候选序列、终选路线和转移数保持一致。差分出现在猎杀者击杀终局的预测摘要。两条首胜用 7 和 16 次转移，后续 F4 用 105 和 496 次，终选为 35 和 59 HP。敌方侧根及额外 `24a989ab…` 哨兵的 F3B/F4 输出排除计时后逐字段一致。修复只影响原语义错误的预测字段。独立原生证据对应表中固定前缀，F4 配对保留预测证据。

## 版本与运行边界

| 二进制 | SHA-256 |
| --- | --- |
| 冻结 Solver 0.51.5 | `d286a18c7c0a06769aa636ec00cac53f3fb71de749028858c1e1a7062282ab13` |
| E3F Release Solver | `cea50e9570edbed06c7f0502fdc5949ba3846ee64605f4891b32768b4ef3d51c` |
| 隔离对照宿主 | `9d55a41b954342c1279d174324223deedaa528d8507695d033b1f17a7b18f7e9` |
| 原生 sts2.dll | `62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3` |

原版和修复版使用不同的 DLL 路径，实验没有部署到 Steam。B1B 生产入口继续绑定冻结 Solver 哈希，保留 E3 风险标记。将来启用修复版应显式切换并核对已加载哈希，完成 B1B 常驻专项后再按版本调整该标记。未追认旧预测或修改历史 L3 标签。敌方侧 `Y`／`AttackStarts` 属于仍保留的严格终局差分；其它未测终局机制仍按原合同核对。

## 复现

仓库根使用本地 CS1 固定源码、原生 DLL、RitsuLib 及 S2B 开发归档。构建脚本复制隔离源码并禁用部署，运行需新输出目录。游戏和 RitsuLib 可通过 `--game-data`、`--ritsu` 参数指定。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
python -X utf8 experiments/m1-e3f/build_solver.py logs/m1-e3f/release-repro
python -X utf8 experiments/m1-e3f/build_host.py
python -X utf8 experiments/m1-e3f/run_probe.py logs/m1-e3f/release-repro logs/m1-e3f/acceptance-repro
python -X utf8 -m pytest experiments/m1-e3f/test_predator_fix.py experiments/m1-e3/test_terminal_audit.py -q
```

逐步原始对照与配对搜索记录见 [results.json.gz](../experiments/m1-e3f/results.json.gz)。隔离 Release 构建、定向实机前缀和搜索配对及 3 项定向测试通过。未打开验证或封存测试根，未运行全量 pytest、五角色批次或大规模基准。
