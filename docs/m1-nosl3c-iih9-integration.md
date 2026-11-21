# II-H.9 累积规则集成验收

集成复放、重采、v4 和战斗夹具锁定 Solver `0.51.5-iih.8.1`、II-H.7 Headless 与 CoreCLR 9.0.7。[逐根证据](../experiments/m1-nosl3c-iih9/evidence.json)包含两个 DLL 的 SHA-256 和原生身份。

## 冻结历史

严格认证 **42/65**，21 胜、21 死。原 38 条全部保留。新增 II-C `0:000019` Living Fog、II-D `0:000002` Fogmog、II-D `0:000010` Hunter Killer 三条死亡和 II-E `2:000001` 吞噬暗影／Flutter 胜局。

II-E `0:000003` Sovereign Blade 在归档索引 28 仍是 `public_prefix_difference`。独立定向复放确认旧手牌漏掉修复后新生成的刀，随后按原卡牌、费用和目标提交最后一手。29 个原动作的 25 个稳定续体均精确匹配，最终进入胜利奖励。该路线的冻结记录与旧行为 logp 未进入训练。

八条原风险仍为 `solver_execution_risk`，原因均为 `prediction_unsupported`。十四条原数据缺口维持 10 条只有前缀、3 条无可重建路线、1 条旧执行失败。冻结复放无新增退化。

## 独立重采

| 样本 | 旧准入 | 新准入 | 其余实际分类 |
| --- | ---: | ---: | --- |
| 16 根 | 10/16 | 11/16（10 胜、1 死） | 2 不支持、1 E3 实差异、1 原生回合超时、1 执行错误 |
| 60 根 | 44/60 | 45/60（28 胜、17 死） | 7 不支持、4 原生差异、3 E3 实差异、1 达到动作预算 |

根、策略、采样配置和动作预算沿用旧套件。两组实测轨迹的公开观察、动作、行为 logp 和长度均逐条相同。16 根新增 `0:000015` 旧归档索引 29 的分歧为致死吞噬暗影多留一层 Power。60 根新增 `1:000017` 旧归档索引 17 的 Slimed 动作前，原生公开菜单漏掉 Void Form 折扣下的 The Smith。两处均符合已验证的规则修复。16 根的回合超时 `0:000001` 与执行错误 `0:000004` 沿袭基线。60 根无环境失败。

## v4 与最终测试

按原配置完成冷跑两次更新，并从独立运行的第一步事务恢复到第二步。每次更新使用 11 条新采集的严格认证轨迹。两份账本完整性检查通过。现有 `compare_journals.py` 确认 32 条根记录的公开轨迹、行为 logp、资格及三个事务快照逐字节一致。快照覆盖模型、Adam 和 Torch RNG。最终模型 SHA-256 为 `93230f45fa62f3abf075027b8290b3533c4c3e392add836828cc3fb9c1fa0d8f`，行为 logp 最大复算误差为 `2.384185791015625e-07`。训练入口仅消费本次重采账本，优化器核验精确资格。

六组定向原生验证全部通过，覆盖吞噬暗影非致死、Gas Bomb、Fogmog Power、Void Form 菜单、Tyranny/Furnace 正负例和 Sovereign Blade 历史路线。

II-H.9 首次主测试为 **158 通过、6 失败、1 跳过**。常规 Headless 被构建到较浅的隔离输出目录，`LocLookup` 从 DLL 目录上溯五级后未找到本地化资源。首个失败在正常到达 Boss 奖励后用英文名查找 Offering 时抛出 `StopIteration`。其余失败也依赖本地化的 Offering、Neow 或 Strike 名称。此前误将主测试连到仅支持合成战斗的宿主，常规游戏命令被拒。两份输出分别保留在 `logs/iih9-pytest-final.log` 和 `logs/iih9-main-pytest.log`。截至 II-H.9 首次提交，全量验收基线仍为 II-H.2。

## II-H.9.1 正式收尾

原常规 Headless 产物逐文件复制到 `logs/iih9-main-host/bin/Debug/net9.0`，DLL SHA-256 与首次测试相同。部署目录上溯五级到达仓库根，LocLookup 成功加载中英资源。原失败的六项全部通过，连同默认语言测试共七项通过。随后一次完整主测试结果为 **164 通过、1 跳过、0 失败**。

Solver、II-H.7 战斗宿主和 CoreCLR 9.0.7 保持原验收身份，直接复用 II-H.9 战斗、重采与训练证据。最新全量验收基线提升为 Solver `0.51.5-iih.8.1`、II-H.7 战斗宿主及上述常规宿主部署。 [收尾通过证据](../experiments/m1-nosl3c-iih9/main-tests-followup.json)

## 最小复现

在仓库根执行，使用已锁定的隔离构建及新输出目录。证据导出约定使用如下输出名，支持 `--logs` 指定日志根。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$s = 'logs/m1-nosl3c-iih8-final'
$h = 'experiments/m1-nosl3c-iih9'
$l = @('logs/nosl3c-iic-random-final','logs/nosl3c-iid-release-independent','logs/nosl3c-iie-broad')
python "$h/run.py" replay logs/iih9-archive @l --solver $s --workers 2
python "$h/run.py" train logs/iih9-pair16 --solver $s --suite pair16 --workers 2
python "$h/run.py" train logs/iih9-holdout --solver $s --suite holdout --workers 2
python "$h/run.py" train logs/iih9-cold --solver $s --suite e3-update --workers 2
python "$h/run.py" train logs/iih9-resume --solver $s --suite e3-update --workers 2 --through-update 1
python "$h/run.py" train logs/iih9-resume --solver $s --suite e3-update --workers 2
python experiments/m1-nosl3c-iih3-stabilization/compare_journals.py logs/iih9-cold/training.sqlite logs/iih9-resume/training.sqlite > logs/iih9-journals.json
python "$h/run_native_fixture.py" experiments/m1-nosl3c-iih4/verify_shadow.py logs/iih9-fixture-shadow --solver $s
python "$h/run_native_fixture.py" experiments/m1-nosl3c-iih5/verify_lifecycle.py logs/iih9-fixture-gas --solver $s
python "$h/run_native_fixture.py" experiments/m1-nosl3c-iih6/verify_lifecycle.py logs/iih9-fixture-death --solver $s
python experiments/m1-nosl3c-iih7/verify_legality.py logs/iih9-legality --solver $s
python experiments/m1-nosl3c-iih8/verify_forge.py logs/iih9-forge --solver $s
python experiments/m1-nosl3c-iih8/verify_history.py logs/iih9-blade --solver $s --ledger $l[2]
python "$h/export_evidence.py" "$h/evidence.json"
```

主测试用同一份修订后的 `RunSimulator.cs` 构建支持完整游戏命令的常规 Headless。

```powershell
$env:PYTHONPATH = (Resolve-Path logs/iig-completion-test-deps).Path
$env:DOTNET_CLI_HOME = (Resolve-Path logs/dotnet-home).Path
$env:NUGET_PACKAGES = (Resolve-Path logs/nuget-packages).Path
$env:PATH = (Resolve-Path logs/m1-review-dotnet).Path + [IO.Path]::PathSeparator + $env:PATH
$source = (Resolve-Path logs/iih9-main-host).Path
$dest = Join-Path $source 'bin/Debug/net9.0'
New-Item -ItemType Directory -Path $dest | Out-Null
Get-ChildItem -LiteralPath $source -File | Copy-Item -Destination $dest
python -c "from pathlib import Path; import sys; sys.path.insert(0, 'python'); import headless_runtime, pytest; headless_runtime.ENGINE = Path('logs/iih9-main-host/bin/Debug/net9.0/Sts2Headless.dll').resolve(); raise SystemExit(pytest.main(['-q', 'tests']))"
```

已部署时可直接执行测试命令。若缺少常规宿主的源产物，可用 `dotnet build src/Sts2Headless/Sts2Headless.csproj -o logs/iih9-main-host -p:NuGetAudit=false` 构建后再部署。
