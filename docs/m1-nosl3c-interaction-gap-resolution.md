# M1-NOSL3C-II-G 接管执行续体与交互归因

基线 `be91500`，STS2 0.113.1／Build 26660232，CoreCLR 9.0.7。隔离构建基于 Torch1230 0.51.5 及前序镜像。现有 II-A 至 II-F 入口和证据仍由旧代码复现。

## 已验证的公开抽牌堆选择

Solver 在实际执行期间产生选择规格。规格自带公开许可，执行桥仍须拿到该请求对应的检查点才能发布。Seeker Strike 随机选取的子集可见，使用独立原生选择状态核验数量、Card ID、升级和显示顺序。锁定原生程序集的 `SeekerStrike.<OnPlay>d__5.MoveNext` 先洗牌再取样，将成员筛选器传给 `CardSelectCmd.FromCombatPile`。`FromCombatPile` 在抽牌堆回调中按稀有度、卡牌比较结果依次排序。两个原生根验证了呈现顺序，其中一个根可区分抽样次序与最终菜单次序。搜索路径保留原来的过滤和排序行为。公开端只渲染已许可子集，私有来源牌序、RNG 及实例令牌留在检查点中。

在交互上下文，已标记的揭示请求由真实待决选择承载，避免将同一个未答请求同时标成预测失败。其它预测风险继续生效。没有捕获检查点、来源可见性未验证或来源中出现与已揭示候选难以区分的实例时，停止并保留原因。原生与预测第二次出牌的重复实例负例显示，即使菜单的 Card ID／升级相同，移除不同的物理实例也会造成未来抽牌顺序不同。该负例不进入资格。

原始 Solver 离线直接复放同一张牌，从 `PendingChoice` 接收已验证原生选择对应的实例令牌后可继续至稳定边界。原始 Replay 使用历史上下文顺序，将令牌按原始上下文重绑，选中实例保持相同。NOSL 通过现有执行帧保存、发布、恢复和清理该请求。独立原生全胜局共有 10 个精确匹配的稳定边界，终局资源同样匹配。重复实例负例在首次精确匹配后、第二次出牌的待决边界停止。

不同隐藏牌序的配对在揭示前产生相同的 v4 观察和概率。另用两个原生 RNG 不同的根，通过 Acrobatics 实际抽牌和弃牌请求，验证了相同公开历史在出牌前及揭示后分布均逐项相等。关闭挂起会话后原生起点不变。训练采集和审计仍复用白名单投影，新增私有追踪只供诊断侧使用。

## 执行审计与剩余边界

私有追踪记录阻碍类型、实际动作、源牌区、效果、执行时机、候选数及检查点是否取得。普通玩家输入和已有手牌、弃牌堆、生成牌及嵌套选择仍使用原状态机。旧 II-F 死亡规则的字段和前缀条件完整保留。重新验证后使用独立构建哈希和规则标识。没有把 `FREE_ATTACK_POWER` 底层差异放入等价规则。

保留其它抽牌堆请求的守卫。回合开始的 Draw／MoveToHand 和 CLEANSE 的 Draw／Exhaust 已取得检查点，仍须独立验证公开候选和实例绑定。三条未取得检查点的路线来自回合开始的 Tyranny、SURVIVOR、BRAND。最小已保存复现使用覆盖矩阵中的根和相同动作前缀。Tyranny 经 `TurnStartPowerSupport` 调用 `TurnStartChoiceSupport.Resolve` 后请求追加回合续体。SURVIVOR 和 BRAND 均有 `CardChoiceSupport.GetSpec` 和既有手动卡牌声明。实际桥只接管完整的 `ExecutionReplayTailFrame` 和已消费选择前缀匹配的续体。现有追踪确认请求到达该桥，尚未区分是尾帧缺失、前缀不匹配还是执行器拒绝分叉。为这些路径推进覆盖，需要单独诊断各捕获拒绝分支，并用独立原生测试核验恢复及副作用。

卡牌执行中的二次目标、`ModDefined`、更广泛的无剪枝菜单导出仍未完成。既有动态敌人目标由 II-D 私有实体身份重新绑定。新构建复验了全队能量和本局无可选盟友的拒绝路径。

中间构建的原生验证还覆盖了重复弃牌、升级、回合开始弃牌及生成，Acrobatics／Prepared／Armaments／Tools of the Trade／Quasar 分别以 15／9／14／13／21 个精确稳定边界完成胜局。Decisions Decisions 的自动出牌嵌套选择验证到 36 个稳定边界，死亡时严格散列不符。Burning Pact 原生对照停在 22 个匹配边界后的死亡差异。证据保留各自构建哈希。没有为这些中间探针建立新的死亡例外。

## 冻结复放与独立抽样

| 复放结论 | II-C | II-D | II-E | 合计 |
| --- | ---: | ---: | ---: | ---: |
| 精确匹配 | 2 | 13 | 5 | 20 |
| 死亡窗口语义匹配 | 5 | 7 | 1 | 13 |
| 实质差异 | 2 | 2 | 2 | 6 |
| Solver 预测风险 | 1 | 4 | 3 | 8 |
| E3 终局规则风险 | 2 | 1 | 1 | 4 |
| 路线或后续动作缺失 | 7 | 0 | 0 | 7 |
| 来源可见性未确认 | 1 | 1 | 1 | 3 |
| 请求存在且检查点未取得 | 0 | 1 | 2 | 3 |
| 引擎或工作进程失败 | 0 | 1 | 0 | 1 |

22 条原未确定路线均有逐条回放或证据缺口记录。其中 8 条触发预测风险，4 条触发 E3，4 条缺少可核验的后续动作，3 条带未验证的公开范围，3 条没有检查点。它们没有取得新增同路线终局或准入。本次没有进行同根重新采样。矩阵同时保留已提交动作、最后稳定边界、决策阶段、目标类型和 II-F 原 Solver 对照。缺失的历史动作与对照证据保留为空。原始 `PendingChoice` 只说明存在未答请求。另有 6 条复放确认实质不一致，`CASCADE` 的 `FREE_ATTACK_POWER` 差异仍在此列。

独立种子 `718606` 以 999 HP 运行全角色卡池目录抽样的 16 条尝试。8 条获准，7 胜和 1 死，认证分为 7 精确和 1 语义。其余为 3 条 E3、2 条未支持、1 条实质差异、1 条原生审计失败及 1 条执行错误。该批不优化。Seeker Strike 的原生证据来自独立的 schema 1 无色牌夹具。全角色卡池抽样使用 schema 3 的角色目录。

## v4 集成与回归

沿用 v4 的公开决策及行为概率协议。两次短程更新使用 6 条认证轨迹，其中 3 条含显式选牌与确认。恢复与不中断运行的公开轨迹、模型、Adam 和 Torch RNG 逐项一致。第二次更新的行为 logp 最大复算误差为 `1.19e-7`。事务账本记录认证模式、规则和路线标识。`exact`、`semantic`、`diagnostic` 沿用 II-F 的准入区别。

全量 pytest 为 162 通过、1 跳过。NOSL3A／3B／3C-I／Ib 定向测试为 6／4／5／4，F4／LS2A／LS2B 为 6／7／5，LS2A 另有 6 个子测试通过。II-A 至 II-F 分别复跑终局资格、公开等价、冻结见证、目标、死亡正负例和语义正负例。均使用 CoreCLR 9.0.7 运行原生宿主。

逐路线数据在 [coverage.json.gz](../experiments/m1-nosl3c-iig/coverage.json.gz)。[evidence.json](../experiments/m1-nosl3c-iig/evidence.json) 含原生探针、随机批次、模型恢复、构建及源文件哈希。

## 复现

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$iig = 'experiments/m1-nosl3c-iig'
$solver = 'logs/m1-nosl3c-iig-certified'
python "$iig/build_solver.py" $solver
python "$iig/build_host.py"
python "$iig/probe_reveal.py" logs/iig-reveal --solver $solver
python "$iig/verify/native.py" logs/iig-native --solver $solver
python "$iig/trace_archive.py" logs/iig-archive logs/nosl3c-iic-random-final logs/nosl3c-iid-release-independent logs/nosl3c-iie-broad --solver $solver
python "$iig/run.py" logs/iig-independent --solver $solver --config "$iig/independent.json" --mode semantic
python "$iig/run.py" logs/iig-check --solver $solver --config "$iig/integration.json" --mode semantic --through-update 1
python "$iig/run.py" logs/iig-check --solver $solver --config "$iig/integration.json" --mode semantic
python "$iig/run.py" logs/iig-control --solver $solver --config "$iig/integration.json" --mode semantic
python experiments/m1-nosl3c-iib/verify_resume.py logs/iig-check logs/iig-control
python -m pytest -q
python -m pytest -q experiments/m1-nosl3a/test_nosl3a.py experiments/m1-nosl3b/test_nosl3b.py
python -m pytest -q experiments/m1-nosl3c/test_nosl3c.py experiments/m1-nosl3c-ib/test_performance.py
python -m pytest -q experiments/m1-f4/test_quality.py experiments/m1-ls2a/test_ls2a.py experiments/m1-ls2b/test_ls2b.py
python experiments/m1-nosl3c-iif/validate.py
```

旧账本由 [II-F 报告](m1-nosl3c-solver-adapter-audit.md) 所列冻结输入生成。语义规则绑定已核验 DLL 哈希；其他构建仍可调用精确审计。
