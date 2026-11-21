# II-I.9B 累积构建集成验收

II-I.9B 通过，正式全量验收基线提升为 Solver `0.51.5-iii.8`、II-H.7 战斗宿主、CoreCLR 9.0.7 和 STS2 v0.113.1 Build 26660232。常规主测试继续使用 II-H.9.1 已验证的部署。两个战斗产物 SHA-256 及运行身份均已核验，详见[结构化证据](../experiments/m1-nosl3c-iii9b/evidence.json)。

冻结历史与八根统一重采直接引用 [II-I.9A](m1-nosl3c-iii9a-risk-acceptance.md)。原 42/65 条严格认证及终局戳全部保留，八个原始阻断前缀精确匹配，八根重采为 2 胜、4 死严格认证。Hammer Time+ 路线的延迟抽牌 Power 差异和 Quasar/Panache 预测不支持各保留一条见证。

## 独立 16/60 根重采

| 套件 | II-H.9 | II-I.9B | 本轮其余分类 |
| --- | --- | --- | --- |
| 16 根 | 11/16（68.75%） | 11/16（68.75%，10 胜、1 死） | 1 预测不支持、1 原生续体差异、1 E3 终局差异、1 原生回合超时、1 执行错误 |
| 60 根 | 45/60（75%） | 50/60（83.33%，32 胜、18 死） | 3 预测不支持、3 原生状态或菜单差异、3 E3 终局差异、1 达到动作预算 |

所有原严格准入根保留认证。配置哈希、根、行为种子和初始模型匹配，优化关闭。76 根的公共观察、动作和行为 logp 在共同长度内逐步相同。五根延伸了原来被截断的轨迹，首个新增决策逐根记录。

- 16 根 `0:000009` 越过 Legion of Bone 的旧阻断。新轨迹在索引 50 的 Rattle 后出现存活敌人状态差异，严格拒绝。原超时 `0:000001`、执行错误 `0:000004` 和 E3 差异 `0:000006` 保留。
- 60 根 `0:000017`、`1:000011`、`1:000023`、`1:000024` 越过 Hammer Time、Underworld、Glimpse Beyond 和 Plot 的旧预测阻断并获认证。
- 60 根 `0:000006` 用相同公开轨迹通过严格原生复放。旧审计在索引 18 的 Wrought in War 后显示 Sovereign Blade 伤害为原生 66、预测 75。本轮完整原生终局获证，证据尚未隔离导致该边界恢复的具体镜像。
- 60 根未发生执行错误或超时。

## v4 冷跑与恢复

从本轮 16 根新账本导入首次更新的已审计轨迹。导入前检查根序列、构建及协议、源代码哈希和初始快照。冷跑在一个进程中完成两次更新，恢复路线在第一次提交后退出并重新启动。两路第二次更新均独立按更新后的策略实时采集。

`compare_journals.py` 确认 32 条根记录的公开轨迹、行为 logp、资格及三个事务快照逐字节一致。快照包含模型、Adam 和 Torch RNG。两次更新分别使用 11、12 条严格认证轨迹，最大 logp 复算误差均为 `2.384185791015625e-07`。最终模型 SHA-256 为 `6edf1a76fba9579a05dabe42d798b8dcb7ad7d6302862775effb0ddbdfbe34e2`。

## 完整主测试

常规宿主为 II-H.9.1 部署的 `logs/iih9-main-host/bin/Debug/net9.0/Sts2Headless.dll`，哈希与 II-H.9.1 一致。完整主测试 **164 通过、1 跳过、0 失败**，覆盖英文、中文和默认语言。常规宿主与采样所用战斗宿主分别绑定。

## 最小复现

从仓库根运行。使用新的日志前缀避免覆盖已有产物。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/m1-nosl3c-iii8-candidate'
$h = 'experiments/m1-nosl3c-iii9b'
$r = 'new-iii9b'
python "$h/train.py" "logs/$r-pair16" --solver $s --suite pair16 --workers 2
python "$h/train.py" "logs/$r-holdout" --solver $s --suite holdout --workers 2
foreach ($mode in @('cold','resume')) {
    python "$h/train.py" "logs/$r-$mode" --solver $s --suite e3-update --workers 2 --through-update 0
    python "$h/seed_pair16.py" "logs/$r-pair16" "logs/$r-$mode"
}
python "$h/train.py" "logs/$r-cold" --solver $s --suite e3-update --workers 2
python "$h/train.py" "logs/$r-resume" --solver $s --suite e3-update --workers 2 --through-update 1
python "$h/train.py" "logs/$r-resume" --solver $s --suite e3-update --workers 2
python experiments/m1-nosl3c-iih3-stabilization/compare_journals.py "logs/$r-cold/training.sqlite" "logs/$r-resume/training.sqlite" > "logs/$r-journals.json"
$env:PYTHONPATH = (Resolve-Path logs/iig-completion-test-deps).Path
$env:DOTNET_CLI_HOME = (Resolve-Path logs/dotnet-home).Path
$env:NUGET_PACKAGES = (Resolve-Path logs/nuget-packages).Path
$env:PATH = (Resolve-Path logs/m1-review-dotnet).Path + [IO.Path]::PathSeparator + $env:PATH
python -c "from pathlib import Path; import sys; sys.path.insert(0, 'python'); import headless_runtime, pytest; headless_runtime.ENGINE = Path('logs/iih9-main-host/bin/Debug/net9.0/Sts2Headless.dll').resolve(); raise SystemExit(pytest.main(['-q', 'tests']))" *> "logs/$r-main-pytest.log"
python "$h/export_evidence.py" $r
```
