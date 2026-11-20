# M1-NOSL3C-II-G Completion 通用交互恢复与严格准入

基线 `44518d9`。本阶段使用 STS2 v0.113.1／Build 26660232、CoreCLR 9.0.7 和从 Torch1230 v0.51.5 派生的隔离版本 `0.51.5-iig.2`。现有 II-A 至 II-G 可独立复现。新构建、双端原生探针和 v4 入口位于 [实验目录](../experiments/m1-nosl3c-iig-completion/)。

## 执行帧和公开选择

交互桥优先采用原 Solver 的执行尾帧及其消费完毕的选择前缀。失败后记录首次捕获拒绝、检查点拒绝和请求的阶段。对缺少尾帧且预测无风险的真实选择，保留当前动作开始前的私有稳定快照，复用 Solver Replay。提交后从同一快照分叉并加入外部选择，对照开启捕获和普通 Replay 的续体文本、风险、历史事件类型序列、死亡实体和候选私有位置。两个分支的结果必须一致。分叉各自持有副作用，求解器会话只安装其中一个。后续请求仍循环经过捕获、公开、选择和继续。策略编码继续通过已有公开字段白名单。

| 冻结见证 | 第一次执行限制 | 当前原生复放 |
| --- | --- | --- |
| II-D 0/000014 Tyranny | 稳定动作前状态仓库含 `VigorPowerMirrors.State`，Solver 保守禁止捕获 | 回合开始消耗由 Replay 继续。提交选择后续体精确 |
| II-E 0/000001 SURVIVOR | 稳定动作前状态仓库含 `CardPlayPairPredictionState`，同样拒绝捕获。首个 Anticipate 还存在原生 Power 顺序差异 | 通用临时敏捷路径修正应用顺序。弃牌由 Replay 继续并精确匹配 |
| II-E 2/000004 BRAND | 空手牌触发零候选的计划占位符。旧 Solver 生成请求时没有记录选择帧 | 零候选由执行器完成原有空计划，策略无额外决策。整个可重建前缀精确匹配 |

原始 Solver 对这三条计划都先到达 `PendingChoice`，为相同动作前缀提供已核验选择后都退出到稳定边界，BRAND 的参数是空选择。历史在这些边界之后没有完整动作记录，因此所补选择以诊断输入单列。原生复放同时核验了同一动作期间再次打开选择的情况。

原生 `Cleanse.OnPlay` 和 `ForegoneConclusionPower.BeforeHandDraw` 均调用无遮蔽筛选器的 `CardSelectCmd.FromCombatPile`。可见候选按稀有度和卡牌比较结果显示，逐个匹配原生位置。两个同外观 Strike 的点击位置经原生、预测两端独立验证，移除后的 `D` 顺序确实不同，两条各自精确匹配。同一机制完成了 13 个精确边界的原生胜局，同根补采另有选过抽牌堆候选的认证死亡。Foregone Conclusion 和 CLEANSE 的冻结前缀均通过新选择继续。Seeker Strike 的原有胜局和重复实例负例复跑，随机抽样中未证明的物理实例对应关系仍然拒绝。

`ModDefined`、卡牌中途二次目标及其他未证明可公开的来源仍为显式边界。复验覆盖已有全队目标和无合法盟友的情况。

## Solver 与原生差异

**CASCADE 的旧差异已修复。** 旧原生复放首次分歧位于 II-C 0/000013 的零基动作 24。攻击消费现有免费攻击层后，原生 `PowerCmd.Apply` 检查 `CombatManager.IsEnding`，跳过最后一击后再次应用的 Power。旧 Solver 的声明式效果表继续应用。共享表现在检查 Solver 的终局条件，原路线由原生差异变为精确胜局。该路线此前所有非致死边界继续精确匹配。

其余五条旧实质差异保留，分别涉及 Living Fog 召唤物存活、Fogmog 终局的免费攻击、Hunter Killer 菜单、Regent 的 Sovereign Blade 手区和 Consuming Shadow／Flutter 状态。Fogmog 的差异方向和发生窗口与 CASCADE 不同。

8 条 `solver_execution_risk` 都带动作、风险枚举和首次拒绝位置。原 Solver 对八条固定前缀均报告风险。7 条独立原生前缀观察到了具体的状态差异，涉及 Power、球、Osty、牌区和 RNG。PLOT 路线在更早位置已有菜单差异，后续预测风险仍单列。两端实际状态可从机器证据定位。

四条 E3 的原生战斗都在敌方侧锁定胜利，再提交结束回合仍停在奖励并保持锁定资源与续体。两个 Nibbits 见证仅有 `Y` 差异，Exoskeletons 有 `Y` 与 `AttackStarts`，Corpse Slugs 还存在 Power 差异。现有证据确认了终止边界，但未验证不同终局钩子组合的清理与奖励语义。四条保留 E3 隔离。本阶段沿用旧死亡规则的条件，在新版本上逐条重证，保留 `exact`、`semantic`、`diagnostic`。

II-D 0/000019 所报 worker 异常由宿主早期的 `Neutralize.OnPlay` 替换前缀触发。Solver 正确拒绝未知的 Gameplay 补丁。新隔离宿主使用原生方法，建根和执行成功。旧样本缺少原动作。新线路在第六个决策处因 SNEAKY 预测缺口停止。

## 65 条冻结路线及独立验证

| 同路线结果 | 数量 |
| --- | ---: |
| 完整精确胜局 | 16 |
| 完整精确死亡 | 5 |
| 已证死亡语义等价 | 13 |
| 有前缀且缺少完整原玩家动作 | 10 |
| 无原动作 | 3 |
| Solver 预测风险 | 8 |
| 保留旧实质差异 | 5 |
| E3 隔离 | 4 |
| 原 worker 异常导致无历史轨迹 | 1 |
| 总计 | 65 |

完整认证从 33 增至 34，新增的是 CASCADE 同路线胜局。31 条原路线仍无严格完整终局。三个捕获缺口和三个抽牌堆可见性缺口均已越过原先的执行限制，实际后续动作仍有缺失。矩阵单列独立原生前缀和补充选择。34 条完整轨迹中有 16 胜和 18 死。

同根重采 14 条，9 条完整准入，含 3 胜和 6 死。7 条原动作缺失或不完整的根有 5 条新轨迹准入。另 4 条新准入来自先前捕获或可见性受阻的根。新轨迹单独统计，其中包含 Tyranny 的认证死亡和 Survivor 的精确胜局。

II-G 的独立 16 根配对仍为 8/16。两个全卡池新种子各 30 条，原生角色 HP 为 22/30，高 HP 999 为 19/30。合计 41/60 准入，24 胜、17 死，29 精确、12 语义。另有 7 未支持、6 E3、5 实质差异、1 动作超限。全部 60 根成功构造，覆盖五角色与三幕。40 条实际遇到多敌菜单，12 副牌组存在重复牌，58 副含升级。新种子提供扩展范围的独立证据，配对样本未发现准入率提升。多种已知阻碍仍存在，尚不足以全面启动高 HP 大规模训练。

## v4 与证据

v4 沿用现有模型、公开动作、奖励、Critic 与优化过程。两次短程更新、6 条认证轨迹通过分段恢复与不中断运行逐项比较，覆盖公开轨迹、模型、Adam 和 Torch RNG。另以同根补采批次做了一次工程更新，9 条认证轨迹含新恢复的多阶段选择，共 167 次决策，行为 logp 最大复算误差为 `1.19e-7`。事务日志按新构建及认证规则识别轨迹。

[配对矩阵](../experiments/m1-nosl3c-iig-completion/paired-archive.json.gz) 含最早阻碍、原生首差异、原动作、补充诊断、分角色、幕和遭遇统计。[新轨迹矩阵](../experiments/m1-nosl3c-iig-completion/new-trajectories.json.gz) 独立记录同根补采和留出样本。[原生证据与构建哈希](../experiments/m1-nosl3c-iig-completion/evidence.json) 含正负探针、原始 Solver Replay、终局窗口和恢复结果。

## 复现

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$folder = 'experiments/m1-nosl3c-iig-completion'
$solver = 'logs/m1-nosl3c-iig-completion-candidate'
$ledgers = @('logs/nosl3c-iic-random-final', 'logs/nosl3c-iid-release-independent', 'logs/nosl3c-iie-broad')
python "$folder/build_solver.py" $solver
python "$folder/build_host.py"
python "$folder/replay_archive.py" logs/iig2-archive @ledgers --solver $solver
python "$folder/verify/certification.py" logs/iig2-archive/nosl3c-iic-random-final.json logs/iig2-rule-check.json
python "$folder/verify/draw_instances.py" logs/iig2-draw --solver $solver
python "$folder/verify/current.py" logs/iig2-current --solver $solver
python "$folder/verify/terminal_windows.py" logs/iig2-terminal @ledgers --solver $solver
python "$folder/verify/risk_original.py" logs/iig2-risk @ledgers --solver logs/m1-nosl3c-iig-certified
python "$folder/verify/direct_recovery.py" logs/iig2-original @ledgers --solver $solver --case nosl3c-iid-release-independent:0:14 --case nosl3c-iie-broad:0:1 --case nosl3c-iie-broad:2:4
python "$folder/probe_prefix.py" logs/iig2-prefix @ledgers --solver $solver --case nosl3c-iic-random-final:0:11 --case nosl3c-iid-release-independent:0:23 --case nosl3c-iid-release-independent:0:14 --case nosl3c-iie-broad:0:1 --case nosl3c-iie-broad:2:4 --continue-choice
python "$folder/train_completion.py" logs/iig2-pair16 --solver $solver --suite pair16 --mode semantic
python "$folder/train_completion.py" logs/iig2-holdout --solver $solver --suite holdout --mode semantic
python "$folder/train_completion.py" logs/iig2-resample --solver $solver --suite resample --mode semantic
python "$folder/verify/optimize_resample.py" logs/iig2-resample-update --solver $solver
python "$folder/train_completion.py" logs/iig2-resume --solver $solver --suite integration --mode semantic --through-update 1
python "$folder/train_completion.py" logs/iig2-resume --solver $solver --suite integration --mode semantic
python "$folder/train_completion.py" logs/iig2-control --solver $solver --suite integration --mode semantic
python experiments/m1-nosl3c-iib/verify_resume.py logs/iig2-resume logs/iig2-control
```

旧账本的输入见 [II-F 报告](m1-nosl3c-solver-adapter-audit.md)。语义模式绑定已验证的 Solver SHA-256。其余构建可执行精确认证。CoreCLR 9.0.7 作为原生运行时，SDK 继续承担构建。

## 回归

主测试集 162 通过、1 跳过。跳过项仍为旧 S1 夹具的跨房 A/B/A 路线不足。II-A 至 II-G 的原生资格、公开概率、死亡见证、目标和语义正负例已复跑。新构建另外重跑公开 RNG 等价、Seeker Strike、重复实例、E3 终局探针和当前认证规则正负例。NOSL3A／3B／3C-I／Ib 定向测试分别为 6／4／5／4 通过，F4／LS2A／LS2B 为 6／7／5 通过，LS2A 另有 6 个子测试通过。共享原生宿主的五角色各五局均到达正常游戏终局。隔离宿主的测试入口只接收合成战斗。

冻结实验的同名模块需在独立 Python 进程运行。主测试集使用 `tests` 目录。

```powershell
$env:DOTNET_CLI_HOME = (Resolve-Path logs/dotnet-home).Path
$env:NUGET_PACKAGES = (Resolve-Path logs/nuget-packages).Path
$env:PATH = (Resolve-Path logs/m1-review-dotnet).Path + [IO.Path]::PathSeparator + $env:PATH
$env:DOTNET_ROLL_FORWARD = 'LatestPatch'
python -m pytest -q tests
$tests = @('m1-nosl3a/test_nosl3a.py', 'm1-nosl3b/test_nosl3b.py', 'm1-nosl3c/test_nosl3c.py', 'm1-nosl3c-ib/test_performance.py')
foreach ($test in $tests) { python -m pytest -q "experiments/$test" }
$env:STS2_F4_RESULTS = (Resolve-Path logs/m1-f4/final).Path
python -m pytest -q experiments/m1-f4/test_quality.py
$env:STS2_LS2A_PILOT = (Resolve-Path logs).Path
python -m pytest -q experiments/m1-ls2a/test_ls2a.py
$env:STS2_LS2B_NATIVE = (New-Item logs/iig2-ls2b -ItemType Directory -Force).FullName
python -m pytest -q experiments/m1-ls2b/test_ls2b.py
foreach ($role in @('Ironclad','Silent','Defect','Regent','Necrobinder')) { python python/play_full_run.py 5 $role }
```
