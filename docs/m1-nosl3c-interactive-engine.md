# M1-NOSL3C-II-B 交互式战斗执行

基线为 `465fb8a`。游戏为 0.113.1／Build 26660232，运行时为 CoreCLR 9.0.7。独立 Solver 构建从 Torch1230 0.51.5 锁定源码出发。构建脚本保留新增桥接源码和唯一的捕获谓词改动，校验冻结游戏及 Solver DLL，记录编译产物哈希。旧 NOSL 宿主和训练证据继续由原入口复现。

## 执行归属

Solver 有两套相关续体。手动卡牌续体在登记的执行位置捕获卡牌事务。通用执行帧记录内层选择、调用者剩余工作、卡牌引用、历史、死亡集合和回合边界。搜索器使用它们恢复分支，按预算与语义去重候选。这些搜索候选不能作为公开菜单。

交互桥从稳定根开始，仅推进提交的动作，到达已捕获的选择后保留当前快照与检查点。候选直接取自当前挂起请求，按出现序数绑定原始实例。确认时调用 Solver 已有的检查点 Fork 和恢复路径。各级执行帧重映射到子状态；新边界安装后释放上一个快照和检查点。关闭会释放待决状态、稳定子快照和宿主根。普通搜索的捕获谓词依旧生效，交互强制捕获只在本会话主动调用 Solver 时开启。对于没有完整帧或缺少公开可见性合同的边界，宿主进入 unsupported。

v3 公开状态区分 combat 与 choice，提供候选来源、效果、时机、上下限、候选次序及已选索引。策略通过同一 Actor 为当前菜单逐项评分。选择候选和确认分别写入轨迹，每步更新历史。原生隐式全选依据 Solver 的 `IsImplicitAllSelection` 自动恢复，并记录效果类型。状态键、回放计划、RNG 和续体摘要留在传输审计与执行器，Python 策略只接收白名单投影。当前仍使用 v2 的资源和预览基础面，有显式活体不可命中或无法确认 TargetType 时整步拒绝。

## 原生差分与资格

原生资格夹具核对出牌菜单、选择候选次序及上下限，并以独立原生进程执行玩家提交的动作。在一个游戏动作完整结束后对比完整续体摘要；对完整胜局核对锁定 HP 和金币。公开等价性探针从不同 RNG 的起点实际打出过牌，揭示七个候选后获得相同观察、历史和动作概率，关闭尚在等待的会话后原始根不变。

五角色跨三个幕的 15 条代表路线全部达到独立原生胜局，合计 285 次完整动作边界一致。二、三幕使用 240 HP 的资格夹具以完成较长战斗，训练配置未使用这些高 HP 根。另一次正常角色 HP 的 15 条扫描中，首幕五场通过，二、三幕十场在敌人阶段的死亡末帧出现原生差异。专项中，杂技、早有准备、武装、必备工具和类星体完成整场复放。燃烧契约完成 22 个动作边界，抉择，抉择完成 36 个动作边界并连续恢复自动打牌、置顶选择，随后两条路线都在死亡末帧失格。保留已有 E3 敌方侧胜利分类；死亡末帧差异单列，尚无足够证据判断是否与 E3 同因。

## 训练链路

`train_interactive.py` 从真实 v3 菜单采样，按决策写出概率与选择历史，复用冻结的无药水、无遗物损失、梯度检查和 SQLite 根账本。每个根用独立 worker，检查模型权重、Adam、Torch RNG，并以配置、源码与引擎摘要隔离运行身份。集成验收完成两次参数更新，包含选择决策，概率复算误差为零。在更新 1 停止并从独立进程重启，最终四根公开轨迹、各检查点模型、Adam 和 RNG 与连续跑逐项相同。 [构建与训练恢复证据](../experiments/m1-nosl3c-iib/evidence.json)该验收按既有训练约定使用预测反馈。将独立原生验证接入训练根准入仍需完成，覆盖表里的正式训练资格保持 unqualified。

## 剩余边界

Draw 来源候选依然需要原生揭示适配，无法安全公开的候选不透传。未捕获的嵌套分派、未登记选择、独立二次指定目标、不可命中或替换目标仍会失格。当前帧桥允许下一层替换上一层检查点，已验证的嵌套和随机生牌只覆盖上述夹具。矩阵列出 454 个角色／卡牌对和 80 个原生目录遭遇，大部分尚未进行逐动作审计。五角色三幕实测只覆盖代表性普通遭遇。 [卡牌、遭遇与机制覆盖矩阵](../experiments/m1-nosl3c-iib/coverage.json)

## 复现

从仓库根运行，使用原生游戏 DLL 和 RitsuLib。Windows 上指定本地 9.0.7 runtime 执行游戏，系统 SDK 仅用于构建。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
python experiments/m1-nosl3c-iib/build_solver.py logs/iib-solver-repro
python experiments/m1-nosl3c-iib/build_host.py
python experiments/m1-nosl3c-iib/qualify_native.py logs/iib-native-repro --solver logs/iib-solver-repro
python experiments/m1-nosl3c-iib/probe_equivalence.py logs/iib-public-repro --solver logs/iib-solver-repro
python experiments/m1-nosl3c-iib/scan_coverage.py logs/iib-scan-repro --solver logs/iib-solver-repro
python experiments/m1-nosl3c-iib/scan_coverage.py logs/iib-death-repro --solver logs/iib-solver-repro --natural-hp
python experiments/m1-nosl3c-iib/train_interactive.py logs/iib-training-repro --solver logs/iib-solver-repro --config experiments/m1-nosl3c-iib/integration.json --through-update 1
python experiments/m1-nosl3c-iib/train_interactive.py logs/iib-training-repro --solver logs/iib-solver-repro --config experiments/m1-nosl3c-iib/integration.json
python experiments/m1-nosl3c-iib/train_interactive.py logs/iib-control-repro --solver logs/iib-solver-repro --config experiments/m1-nosl3c-iib/integration.json
python experiments/m1-nosl3c-iib/verify_resume.py logs/iib-training-repro logs/iib-control-repro
```

全量 pytest 为 162 通过、1 跳过，EngineProbe 通过本地 9.0.7 运行。S1 夹具少于两个合法 A/B/A 续体，沿用既有跳过原因。

冻结 NOSL 定向回归共 19 项通过。五角色各 5/5 场结束，无崩溃或卡死。
