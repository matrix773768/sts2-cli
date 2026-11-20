# M1-NOSL3C-II-C 训练准入

基线 `ea4f42a`，STS2 0.113.1／Build 26660232，CoreCLR 9.0.7，隔离 Solver 0.51.5-iib.1。研究入口位于 `experiments/m1-nosl3c-iic`。旧宿主及训练协议继续使用原入口。

## 资格规则与账本

每条轨迹由冻结 v3 策略逐步采样。随后从同一规格冷建预测与原生战斗，复放实际提交的索引。核对两份完整原生初态、预测公开历史、原生合法出牌集合和选择菜单、稳定游戏动作边界的完整续体、胜负及锁定 HP、最大 HP、金币和药水槽。策略决策完成后才启动审计，私有续体和首个差异状态单独保存在 `audit/`。

仅当实际轨迹通过上述核验才入选优化。资格键包括引擎身份、公开协议、原始根和实际公开路线。当前模式对正常终局逐条复放，尚未建立能代替完整审计的机制组合认证。未知机制、unsupported、E3、截断和运行失败分别记录。输局同样要求完整锁定证据。在量化运行成本时，应把审计占用的 worker 秒与端到端墙钟分开。

每批由同一冻结模型并行采样，按根位置提交。每条尝试有独立派生的采样种子。审计内容先落盘，SQLite 事务记录其校验值、全量尝试及公开轨迹，遗漏的事务位置可恢复。优化复用冻结损失函数和行为概率复算，模型、Adam 与 Torch RNG 一起持久化。覆盖索引从事务记录和审计哈希重建，目录身份、可构造、可执行、审计边界和终局资格分开记录。单卡出现在已核验路线中只是该路径的证据。

## 随机候选与观察结果

生成器读取当次原生目录，使用角色卡池、前三幕普通遭遇、可配置卡组长度与升级率、允许重复及显式 HP 范围。完整规格、分布版本、生成种子、位置和目录摘要可复现。候选的自然跑局可达性未作假设。

固定种子 4301，四 worker，20 个随机候选全部建根，9 条预测正常结束，另有 2 条 E3 风险和 9 条 unsupported。严格审计只准入 1 胜。8 条原生不一致中，4 条首次出现在敌方阶段死亡动作，其余 4 条在更早的稳定续体发生。9 条 unsupported 包含 4 条 AnyAlly、3 条 AllAllies、1 条 PendingChoice 及 1 条未报出具体原因的边界。端到端 33.82 秒，0.59 尝试/s，审计累计占用 37.50 worker 秒。该分母是工程验收样本。按此资格筛出的单条随机轨迹不足以支撑正式随机训练。

构建入口和策略接口沿用 II-B。本阶段没有新增抽牌堆揭示、二次目标、特殊可命中性或续体帧。尤其 AnyAlly 和 AllAllies 需要准确建模当前友方目标，不能套用敌方槽位。PendingChoice 还需要定位是抽牌堆可见性守卫还是帧捕获失败。

## 独立死亡见证

储君对棘刺蟾蜍的归档根在位置 17 首次出现不同的完整续体摘要，此前 17 个稳定边界一致。最后执行结束回合，两边都判定死亡，末帧 HP 为 0、最大 HP 为 75、能量为 2、格挡为 0。原生播放结束后的 `game_over` 已出现，独立原生审计未收到胜局使用的锁定回调。这只能确定首次可观测差异位于致死回合内，并区分两端可比较的终局表面。逐段伤害、Power 监听与清理顺序尚未定位，无法判断与 E3 是否同因，未实施字段豁免。

## 训练集成验收与剩余范围

用 II-B 的四根集成配置验证严格准入后更新。两个 worker 在更新 1 停止并独立进程恢复，最终公开轨迹与单 worker 连续运行一致，模型、Adam 和 RNG 逐张量一致。当前采用冷 worker、逐条原生审计、冻结标量优化。常驻安全退役、v3 张量批处理、概率抽样认证、机制隔离回滚及面向长期正式训练的扩展仍待完成。

## 复现

在仓库根使用现有 II-B 构建和 .NET 9.0.7 环境。将 `$solver` 指向 `build_solver.py` 的独立输出目录。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$solver = 'logs/m1-nosl3c-iib-solver-v3'
$iic = 'experiments/m1-nosl3c-iic'
python "$iic/run_admission.py" logs/iic-random --solver $solver --config "$iic/random-audit.json" --workers 4
python "$iic/coverage.py" logs/iic-random --solver $solver
python "$iic/replay_route.py" logs/iic-death "$iic/death-witness.json.gz" --solver $solver
$cfg = 'experiments/m1-nosl3c-iib/integration.json'
python "$iic/run_admission.py" logs/iic-resume --solver $solver --config $cfg --through-update 1
python "$iic/run_admission.py" logs/iic-resume --solver $solver --config $cfg
python "$iic/run_admission.py" logs/iic-control --solver $solver --config $cfg --workers 1
python experiments/m1-nosl3c-iib/verify_resume.py logs/iic-resume logs/iic-control
```


## 已执行回归

全量 pytest 162 通过、1 跳过。EngineProbe 使用本地 CoreCLR 9.0.7，S1 缺少两条合法 A/B/A 续体。NOSL3A、3B、3C-I 与 Ib 共 19 项通过，F4 独立再验 6 项，LS2A 7 项另有 6 个子测试，LS2B 5 项。II-A 头槌两条完整原生胜局复验通过，II-B 实际揭示后的公开等价性复验通过。

保存 [资格与恢复证据](../experiments/m1-nosl3c-iic/evidence.json) 和 [压缩覆盖矩阵](../experiments/m1-nosl3c-iic/coverage-evidence.json.gz)。
