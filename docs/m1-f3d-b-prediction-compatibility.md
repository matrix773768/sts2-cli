# M1-F3D-B 冻结样本的预测兼容与原生验收

2026-11-18。基线 `6ea0f09e1512c219917b51364b4677ff4702296a`，STS2 v0.113.1 / Build 26660232，CoreCLR 9.0.7，冻结 CombatSolver 0.51.5。

**S2A 六个冻结搜索根全部得到完整、独立原生验收的胜路，共 122 步逐帧匹配。** 六根从原 Spec 在隔离宿主冷重建，完整公开状态、原生快照、RNG、资源和 live 身份与 S2A 留存的原生记录一致。各根仍使用冻结 F3B C、禁用主动药水和 128 次累计搜索转移上限。

## 两处问题

### strength-early 终局窗口

原路线第 13 步打出火焰屏障，第 14 步攻击后敌人剩 4 HP。第 15 步结束回合，原生胜利回调处敌人 HP 为 0。新增只读观察直接记录到原生第 4 回合由 Player 切到 Enemy。出牌开始总数仍为 11，抽牌总数仍为 22。原生 `HappenedThisTurn` 按当前侧统计，窗口出牌数从 2 变为 0；冻结预测端仍保留上一玩家侧的计数。因此只有 continuation 的 `Y`（预测 `0/0/2/2`，原生 `0/0/0/0`）和 `AttackStarts`（1 与 0）出现差分。

原路线仍在第 15 步被严格拒绝。沿用 F3B 既有的拒绝路线摘要与剩余额度重试，再用 25 次转移找到玩家侧结束的替代胜路，独立核对 10/10 步，累计 40 次转移（15 + 25）。比较字段、比较函数及搜索策略保持原样。原敌方侧胜利窗口依然是冻结预测器的未解决边界。

### poison-early Neutralize

单请求复现了旧宿主的失败。冻结预测器在准备时拒绝 `sts2headless.locpatch` 所安装的 `NeutralizePrefix`，它是 headless 旧版替代动作。新实验入口复用 F2 的定向撤除命令，在该根的搜索、固定预测和独立原生执行进程中恢复原生 `OnPlay`。撤除前后完整 native snapshot 和 live/RNG 审计相等，其他五根及正式游戏路径沿用已有宿主行为。

F3B 可以开始搜索。前两条路线的中和均在第 3 步且通过严格帧比较，但两条路线都在第 9 步、敌方侧胜利回调出现上述窗口差分。该回合相同，出牌开始总数均为 7、抽牌总数均为 14，活跃侧窗口从 3 变为 0。两条路线均严格拒绝。第三条在玩家侧结束，仍含第 3 步原生中和，独立核对 11/11 步，无战损。累计 56 次转移（9 + 18 + 29）。

## 六根结果

| 冻结根 | 累计转移 | 严格通过的胜路 | 搜索及验收墙钟 |
| --- | ---: | ---: | ---: |
| strength-early | 40 | 10/10 | 18.02 s |
| block-hive-stocked | 33 | 33/33 | 8.86 s |
| poison-early | 56 | 11/11 | 26.61 s |
| shiv-lean | 18 | 18/18 | 8.99 s |
| shiv-hive-stocked | 26 | 26/26 | 9.58 s |
| strength-hive-low | 73 | 24/24 | 8.86 s |

墙钟含固定预测和独立原生重放，以及失败候选的成本。六根共 246 次已计转移。整个正式实验 95.58 秒，另含每根开局重建及约 2.24 秒的旧补丁失败对照。隔离构建 8.96 秒，0 错误、7 条既有警告。4 项定向证据回归全部通过（0.24 秒），Python 编译和 Git diff 校验通过。未重生成数据集，未运行全量 pytest 或五角色批次。

本次兼容路径仅撤除受测环境中这个已知 Neutralize 替代 prefix。其他未知 Harmony 补丁仍由冻结预测审计拒绝。敌方侧终局窗口差分、其他选择机制及未测遭遇不在本次验收范围。

## 复现

```powershell
python -X utf8 experiments/m1-f3d-b/build.py
python -X utf8 experiments/m1-f3d-b/verify.py logs/m1-f3d-b/repro
$env:STS2_F3DB_RESULTS = (Resolve-Path logs/m1-f3d-b/repro).Path
python -X utf8 -m pytest experiments/m1-f3d-b/test_compatibility.py -q
```

`verify.py` 默认读取 S2A 本地 `logs/m1-s2a/formal/records.json`，支持用 `--source` 指定保有完整原生根的原始记录。完整搜索履历及原始失败帧留在本地运行输出。版本化摘要保留逐步摘要、窗口观测及计费。 [结构化实测结果](../experiments/m1-f3d-b/results.json)
