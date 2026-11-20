# M1-NOSL3C-II-E 死亡认证与高 HP 战损训练

基线 `083550e`，STS2 0.113.1／Build 26660232，CoreCLR 9.0.7，Solver 0.51.5-iid.1。实验沿用 II-D 的隔离宿主、公开 v3 观察、私有目标绑定和完整原生续体核验。

## 两种终局合同

胜利继续要求合法原生复放、完整续体逐边界一致、胜利锁定回调及锁定资源一致。死亡从独立原生 `game_over` 获得结果，要求 `victory=false`、与预测相同的动作前缀和终局续体、零 HP、同最大 HP、格挡、金币，以及无药水合同。致死动作由公开路线确定。死亡路径只在旧审计已对齐最终完整续体、但胜利锁定不可用时启用。历史见证仍以原始严格字段比较复现，`Y`、`AttackStarts`、召唤物清理与 Power 差异均没有豁免。

独立正例为 1/80 HP 铁甲战士，两次结束回合后死亡，两步原生续体相同。修改公开前缀 HP 的复放被拒，篡改原生终局格挡的死亡合同也被拒。证据说明该受测致死路径完整终止。复杂监听器、召唤物清理及其 RNG 仍受完整续体门槛约束。II-D 的自动打牌 `FREE_ATTACK_POWER`、抽牌堆揭示、二次目标与未捕获续体仍待修复。

## v4 战损与价值合同

净损失为 `max(0, initial_hp - terminal_hp)`。报告分别保存最终 HP、超出初始 HP 的净恢复、最大 HP 变化、引擎累计 HP 损失、回合数和决策数。当前宿主没有独立暴露受伤、主动损血和总治疗事件组成，这三项保留为空。超过初始 HP 的治疗不增加奖励。最大 HP 变化独立报告，净损失仍以实际初始和最终 HP 计算。

支持线性、对数和混合损失。终局奖励在胜利为胜利奖金，在死亡为负死亡惩罚，扣除净战损变换和战斗回合成本。选择菜单数量不影响时间成本。配置应使胜利奖金和死亡惩罚的和覆盖最大计划战损与回合成本，默认课程参数满足 999 HP 和 128 决策范围内的该关系。对数项是凹函数，会改变风险偏好，不能据此推断风险规避。失败审计、截断、unsupported 和 E3 没有回报。当前训练使用无折扣终局目标，测试了势函数望远镜恒等式，运行中不额外发放逐步奖励。

独立有符号 Critic 线性输出条件期望回报。Actor 使用 `R - detach(V)`，每条轨迹 Actor 和熵按决策求和，Critic 按轨迹长度求均值，再按轨迹数归权。变长菜单与轨迹按时间步 mask。冻结采集权重、逐步行为概率复算和模型版本检查继续生效。v4 采用独立初始化，不从旧 Critic 继承参数。

## 严格训练、常驻和恢复

随机根从原生目录构造，课程配置支持 999、200 和角色正常 HP，角色、幕、卡池、升级率、卡组长度、根数、每根轨迹数和优化 microbatch 可配置。工程配置声明了基础攻击与防御卡池，长期课程入口使用原生全池。全池注册与有限配置的工程结果不能互换。三阶段课程参数按配置顺序生效，完整课程未启动。

资格默认逐条独立原生审计。采集预测源及独立预测副本冷建，原生审计进程可在线程内常驻。只有已独立确认胜利才尝试奖励跳过、地图结算、释放观察器及守卫复位。下个热根与另一个冷建根核对完整原生快照。失败、死亡、到期、寿命上限及无法结算时关闭。报告中的热审计数量与预测源冷建数量分别记录。

经校验的 SQLite 事务按批次和位置保存尝试，模型、Adam、Torch RNG 和派生采样种子确定恢复。审计单独落盘，事务关联证据摘要。停止使用输出目录中的 `STOP`，移除后同命令恢复。当前未实现共享机制抽样认证、自动隔离回滚、热预测源复用，以及 per-process CPU／峰值内存与独立前向耗时报告。

## 复现

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$solver = 'logs/m1-nosl3c-iid-solver'
$path = 'experiments/m1-nosl3c-iie'
python "$path/probe_death.py" logs/iie-death --solver $solver
python "$path/run.py" logs/iie-check --solver $solver --config "$path/integration.json" --through-update 1
python "$path/run.py" logs/iie-check --solver $solver --config "$path/integration.json"
python "$path/validate.py" logs/iie-check "$path/integration.json"
```

正式启动使用 `python "$path/run.py" logs/iie-course --solver $solver --config "$path/curriculum.json"`。安全停止执行 `New-Item logs/iie-course/STOP -ItemType File`。恢复执行 `Remove-Item -LiteralPath logs/iie-course/STOP`，再重复正式启动命令。


## 工程验收

| 课程 | 尝试 | 严格胜利 | 严格死亡 | 原生差异 |
| --- | ---: | ---: | ---: | ---: |
| 999 HP | 5 | 4 | 0 | 1 |
| 200 HP | 5 | 3 | 0 | 2 |
| 角色正常 HP | 5 | 2 | 1 | 2 |

三批 611 个策略决策，实际更新使用合格胜负。正常 HP 批的回报包含 −75.49，批量行为概率最大绝对误差 2.39e−7。真实账本以 microbatch 1 和 4 回放，Actor 损失差 1.03e−4、Critic 损失差 4.96e−5、熵差 2.98e−6、裁剪前梯度范数一致。更新后同一样本的动作概率和价值差均为 1.49e−8。200 HP 的专项更新另复放了实际弃牌和消耗选择。

上述 15 次尝试累计 60.34 秒，约 0.249 尝试/s、0.249 完整预测/s、0.166 严格准入/s、10.13 策略决策/s。独立审计累计 56.64 worker 秒，优化 1.09 秒，7 个审计热根、9 次守卫结算成功。该运行规模、独立原生重建成本和证据要求均不同于 3C-Ib 的吞吐测量。

全池审计各 HP 档 5 次。999 HP 三胜准入，200 HP 无轨迹准入，正常 HP 一胜一死准入。其余合计 3 条原生差异、6 条 unsupported、1 条 E3 风险。这是严格准入仍限制广泛训练的直接证据，分母包含所有尝试。

全量 pytest 162 通过、1 跳过。冻结 NOSL 定向 19、F4 6、LS2A 7、LS2B 5，II-A 原生胜局、II-B 公开等价性、II-C 死亡见证和 II-D 目标探针复验。所有原生运行使用 CoreCLR 9.0.7。

批中停止在首批 2/5 条事务提交后生效，模型检查点仍在更新 0。重启完成三批后，15 根公开轨迹、模型、Adam 与 Torch RNG 和连续运行逐项相同。双 worker 全冷对照的同一语义结果也逐项相同。该短程对照全冷累计 65.27 秒，常驻恢复运行 60.34 秒，两组与其它验证并行，耗时只作本机工程测量。

[机器可读验收证据](../experiments/m1-nosl3c-iie/evidence.json)
