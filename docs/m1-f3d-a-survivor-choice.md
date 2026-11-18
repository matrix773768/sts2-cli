# M1-F3D-A Survivor 预测弃牌合同

2026-11-18。基线 `75ca811bef19479751d25fe875548fbfb29aae20`，STS2 v0.113.1 / Build 26660232，CoreCLR 9.0.7，冻结 CombatSolver 0.51.5。

**两个冻结的 S2A Shiv 根均已越过 Survivor 待选边界。** 保持 F3B C、128 次预测转移额度、禁用主动药水，`shiv-lean` 和 `shiv-hive-stocked` 分别以 18 和 26 次转移得到胜路，独立原生严格验收 18/18 和 26/26 步。

[结构化结果与摘要](../experiments/m1-f3d-a/results.json) · [两根原生差分程序](../experiments/m1-f3d-a/verify.py)

## 原因与实现

基线的 F3B 动作菜单只为头槌生成 `PlanCardChoice`。两根的第一步都选择了 Survivor，原生一端会给出合法的手牌弃牌请求，预测一端收到的 `PlayCard` 却没有应答 token。冻结预测器已经具备 Survivor 的原生选择形状和处理逻辑，在缺少 token 时停在 `PendingChoice`。失败发生在选择实例绑定之前，父根仍是可分叉的活动边界。复跑基线得到 9 和 6 次转移后候选耗尽，与 S2A 一致。

修复复用预测器的 `CardChoiceSupport.GetSpec`。仅接受 Survivor 的主动作单张手牌弃牌形状。构造 token 前，从候选列表和来源手牌中排除正在打出的那个原实例，因为回调发生在它离开手牌之后。按原 F2 弃牌价值选最低者，同分按候选顺序。token 绑定 ID、升级、完整状态键、来源出现序号与候选出现序号。每个合法 Survivor 出牌只增加一个确定的选择编码，沿用出牌的单次预测转移预算。独立原生重放沿用 F2/F3A 的 `TeacherChoice`，同时以两个出现序号找到同一对象，并验证原对象进入弃牌堆。头槌的候选排序、F3B 策略、分叉和计费逻辑保持原样。

## 第一处差异与原生证据

两版隔离宿主分别独立冷重建两次。开局公开状态、完整原生 snapshot、RNG、资源和 live 身份跨构建一致。两根在修复前均在首个 Survivor 停于 `PendingChoice`，修复后该步回到稳定的 `active` 原生可比边界，预测风险标记为 false。独立固定预测帧与搜索 continuation 摘要一致。另起原生进程执行固定选择，完整帧逐字段相等。原生决策及 RNG 也与基线宿主使用 F2 自动弃牌的同一步相等。

| 样本 | 原生请求与修复选择 | 选择前后 shuffle / generation / selection / monster_ai |
| --- | --- | --- |
| `shiv-lean` | 4 个候选，选 1。选项 2 为 `BLADE_DANCE`，原实例进入弃牌堆 | 1 / 0 / 0 / 0 |
| `shiv-hive-stocked` | 6 个候选，选 1。选项 4 为 `DAGGER_SPRAY`，原实例进入弃牌堆 | 1 / 0 / 0 / 0 |

重复实例回归复用 `shiv-lean` 的开局。两个 `DEFEND_SILENT` 的状态键完全相同，分别在候选索引 1 和 3。定向固定动作显式选择两种出现序号均为 1 的第二张防御，原生双向绑定在索引 3，验证预约的原实例进入弃牌堆。固定预测与原生完整帧相同，四项 RNG 计数保持不变。

## 搜索与耗时

| 样本 | 基线转移、结果 | 修复搜索墙钟 / 热段 | 固定预测帧 | 独立原生重放 | 结果 |
| --- | --- | ---: | ---: | ---: | --- |
| `shiv-lean` | 9，候选耗尽 | 2.44 / 0.30 s | 2.83 s | 2.30 s | 18 次转移，原生 18/18，28→20 HP |
| `shiv-hive-stocked` | 6，候选耗尽 | 3.29 / 0.40 s | 2.35 s | 2.82 s | 26 次转移，原生 26/26，55→46 HP |

基线两场搜索墙钟分别为 2.31 和 2.39 秒。两条新胜路各触发一次原生 Survivor 选择，终局为实际胜利，敌人 HP 为 0。搜索、固定帧及原生回放分别记录结果，只有完整原生胜路通过才计为胜利。包括基线复现、开局重建、两条完整胜路及重复实例差分，正式运行共 53.17 秒。隔离构建 7.66 秒，0 错误、7 条既有警告。三项定向证据断言通过（0.18 秒），Python 编译与 Git diff 检查通过。本次未执行全量 pytest、五角色批次或策略消融。

覆盖限于主动作的一张手牌弃牌。未新增多选、嵌套选择、回合开始选择、自动触发或 Sly 后续选择，以及其他弃牌来源。两根的实测候选数为 4 和 6，空手牌及单候选行为未单独定向测量。Neutralize Harmony 与 `strength-early` 终局差分保持现有边界。

## 复现

从仓库根运行，按 [项目环境](PROJECT_STATUS.md) 设置本地合法游戏 DLL、CoreCLR 9.0.7、冻结求解器和 pytest。保留原 S2A 的 `logs/m1-s2a-build` 宿主。程序核对它与版本化 S2A 结果的二进制 SHA-256；若需重建基线，应从本报告所列基线提交在原构建路径重建。修复宿主写入独立目录。

```powershell
python -X utf8 experiments/m1-f3d-a/build.py
python -X utf8 experiments/m1-f3d-a/verify.py logs/m1-f3d-a/repro
$env:STS2_F3DA_RESULTS = (Resolve-Path logs/m1-f3d-a/repro).Path
python -X utf8 -m pytest experiments/m1-f3d-a/test_survivor.py -q
```

实际配置取自版本化 S2A 结果，只读取两个目标根。复现输出保存完整冷重建、原始和修复后的搜索、固定预测及原生逐步证据。
