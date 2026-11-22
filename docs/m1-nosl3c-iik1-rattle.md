# II-K.1 — Rattle+ 跨回合攻击计数

正式全量验收基线仍为 Solver `0.51.5-iij.4`。本轮从 II-J.5B 验收提交 `7f9daa6` 的后继 `8388642` 开始，后者已记录基线冻结和 II-J 关闭。定向候选 `0.51.5-iik.1` 的 DLL SHA-256 为 `298045b6a291e91a93f7aa40f60e370af25ecd2b68c71caa5e6506f4447f98ca`。复用 II-H.7 战斗宿主及 CoreCLR 9.0.7。

## 根因与修复

基线从 `logs/iij5b-serial-pair16/training.sqlite` 只读恢复 `0:000009`。索引 0–49 精确匹配，索引 50 的 Rattle+ 在原生只命中一次，目标中型树叶史莱姆从 11 降至 2 HP，小型树叶史莱姆保持 9 HP。Solver 多打一击，中型史莱姆死亡。

`BeginSideTurn` 通过原生 `Player.Osty` 查找需要清零的奥斯蒂，而攻击及 Rattle 的计算从预测状态查找。分支中召唤的奥斯蒂保存在预测状态中，原重置漏过该实例，导致此前回合的攻击在下一回合继续计入。将回合重置改用 `GetOsty(ownerPlayer)`，同时使既有攻击计数和逐目标命中记录的重置指向同一分支实例。其余攻击、伤害、目标和认证逻辑沿用原实现。

## 定向验收

| 检查 | 结果 | 耗时 |
| --- | --- | ---: |
| 基线历史复放 | 索引 50 复现原首差 | 约 9.4 秒（输出目录至报告） |
| 基线／候选最小夹具 | 两回合各打一次 Rattle，中间由 Legion of Bone+ 复活同一奥斯蒂。前四步两版精确。第二次 Rattle 原生一击，Flyconid 从 40 降至 33 HP，基线打两击降至 26，候选精确匹配 | 10.6／9.9 秒 |
| 候选历史复放 | 51 个归档决策、49 个稳定原生边界全部匹配，索引 50 续体戳为 `52e34fd56806646b69da15d6afa6114d35cbd27f132934cbf4c418daaa8f5049` | 11.4 秒 |
| 唯一一次同根重采 | 原模型、行为种子 `9818773004995169335`、预算 128，优化关闭。前 51 个决策记录相同，95 个决策、93 个稳定原生边界，严格胜局 `admissible_predicted_win / exact_native_match` | 20.7 秒 |
| Legion of Bone 召唤回归 | 普通／升级、已有／未有奥斯蒂四例全部通过 | 约 15.0 秒（输出目录至报告） |

候选编译用时 18 分 37 秒，出现一条 CS9124 警告。结果保存在 `logs/iik1-*` 的 `route.json`、`fixture.json`、`0-000009.json` 和 `legion.json`。完整套件沿用 II-J.5B 证据。

## 最小复现

在仓库根使用新的输出前缀。长输出可重定向到独立日志。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$h = 'experiments/m1-nosl3c-iik1'
$r = 'logs/new-iik1'
python "$h/verify_route.py" "$r-before" logs/iij4-solver
python "$h/verify_osty.py" "$r-fixture-before" logs/iij4-solver
python "$h/build_solver.py" "$r-solver"
python "$h/verify_osty.py" "$r-fixture-after" "$r-solver"
python "$h/verify_route.py" "$r-after" "$r-solver"
python "$h/resample_rattle.py" "$r-resample" "$r-solver"
python experiments/m1-nosl3c-iii6/verify_legion.py "$r-legion" --solver "$r-solver"
```
