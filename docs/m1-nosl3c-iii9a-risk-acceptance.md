# II-I.9A 八条风险统一验收

以同一份 Solver `0.51.5-iii.8` 配对 II-H.7 战斗宿主、STS2 v0.113.1 Build 26660232 和 CoreCLR 9.0.7。正式全量验收基线仍为 II-H.9.1。初次核验发现动态导入解析到了 II-H.3 宿主，初次输出保留。正式结果来自显式锁定并核对 II-H.7 宿主哈希的独立输出目录。

## 冻结历史

65 条均纳入复放。II-H.9.1 原有 42 条严格认证全部保留，包括 21 胜、21 死，42 条终局原生戳均与基线一致。14 条原历史数据缺口仍为 10 条仅有前缀、3 条无法重建路线、1 条旧执行失败（II-D `0:000019`）。Sovereign Blade（II-E `0:000003`）仍在索引 28 因旧公开观察中的手牌失配而未获认证。其余八条为本轮验证的风险前缀。

下表八条冻结前缀逐步精确匹配，原始预测阻断均消除。前缀结束时战斗仍在进行，八条冻结记录均无完整战斗认证。表内诊断是前缀上保留的提示，该范围内未观察到相应实际差异。

| 冻结根 | 精确步数 | 残留诊断 | 重采动作数 | 重采严格结果 |
| --- | ---: | --- | ---: | --- |
| II-C `0:000003` | 7/7 | Bulwark | 16 | 死亡 |
| II-D `0:000009` | 1/1 | 无 | 14 | 胜利 |
| II-D `0:000025` | 2/2 | Sic ’Em | 24 | 死亡 |
| II-D `0:000027` | 13/13 | Pull Aggro、Countdown、Delay | 15 | 死亡 |
| II-D `0:000028` | 3/3 | Battle Trance | 12 | 死亡 |
| II-E `1:000000` | 13/13 | Reave、Pull Aggro、Capture Spirit、Slimed | 73 | 胜利 |
| II-E `1:000002` | 1/1 | 无 | 43 | 原生续体实差异 |
| II-E `1:000003` | 8/8 | Void Form、Parry、Monologue | 4 | 预测不支持，第 5 次决策未推进 |

## 八根重采

按对应定向候选的原批次分组，新账本共七份，以保留根位置及其采样种子。配置哈希、行为种子和模型哈希与各自的定向对照一致，预算为 128 动作，优化关闭。八根的动作序列及严格结果均与各自定向候选一致。II-I.5 的两条中间结果曾分别因 Legion of Bone 和 Glimpse Beyond 而预测不支持，由 II-I.6、II-I.7 各自的定向结果接续对照。本轮六根获 `exact_native_match`，没有新增菜单实差异、执行错误或超时。

- **Hammer Time+ 路线**：II-E `1:000002` 的首个实际差异仍在索引 42。打出 Sovereign Blade 后，Solver 额外保留 `DRAW_CARDS_NEXT_TURN_POWER=2`。结果为 `native_difference / semantic_mismatch`。
- **Quasar 路线**：II-E `1:000003` 第 3 次决策打出 Quasar，第 4 次选 Panache，第 5 次 `confirm_selection` 报 `PendingChoice`，详情为 `Candidate is missing from its source`。结果为 `unsupported / semantic_unverified`，尚未进入原生审计。

[逐根结构化证据及构建哈希](../experiments/m1-nosl3c-iii9a/evidence.json)

## 最小复现

在仓库根使用新输出目录。末行可导出复跑产物，省略第二个参数时读取原验收的重采与风险日志。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$h = 'experiments/m1-nosl3c-iii9a'
$s = 'logs/m1-nosl3c-iii8-candidate'
$l = @('logs/nosl3c-iic-random-final','logs/nosl3c-iid-release-independent','logs/nosl3c-iie-broad')
$c = @('--case','nosl3c-iic-random-final:0:3',
       '--case','nosl3c-iid-release-independent:0:9',
       '--case','nosl3c-iid-release-independent:0:25',
       '--case','nosl3c-iid-release-independent:0:27',
       '--case','nosl3c-iid-release-independent:0:28',
       '--case','nosl3c-iie-broad:1:0',
       '--case','nosl3c-iie-broad:1:2',
       '--case','nosl3c-iie-broad:1:3')
python "$h/replay.py" logs/new-iii9a-archive @l --solver $s --workers 2
python "$h/risks.py" logs/new-iii9a-risks $s
python experiments/m1-nosl3c-iii8/verify_root.py prefix logs/new-iii9a-prefix @l --solver $s @c
foreach ($i in @(1,2,3,4,6,7,8)) {
    $script = if ($i -eq 1) { 'verify_roots.py' } else { 'verify_root.py' }
    python "experiments/m1-nosl3c-iii$i/$script" resample "logs/new-iii9a-sample-$i" $s
    if ($LASTEXITCODE) { throw "Resample group $i failed" }
}
python "$h/export_evidence.py" logs/new-iii9a-archive new-iii9a
```
