# II-K.2.1 — E3 球体致胜的回合窗口

起点为 `port/v0.113.1@5bb1ff7`，对照 Solver 为 `0.51.5-iik.1`。候选 `0.51.5-iik.2.1` 继承 II-K.1，DLL SHA-256 为 `05d8bdc649d6e973005344cdf530c22c2bec33c4e6d369cd426e30f4f4054993`。原生证据复用 II-H.7 战斗宿主与 CoreCLR 9.0.7。正式全量验收基线为 `0.51.5-iij.4`。

## 字段语义与根因

`Y` 依次记录当前方与轮次窗口内该玩家抽到的状态牌数、以 0 能量开始的攻击牌数、全部出牌开始数、攻击或技能出牌开始数。`AttackStarts` 记录同一窗口内全部攻击牌出牌开始数。它们都是事件计数，每次开始出牌计一次。

两个见证均在 `end_turn` 的玩家回合结束第一阶段被球体被动打掉最后一个敌人。原生依序等待球体被动和 `DoTurnEnd` 完成，再在第一阶段的 `CheckWinCondition` 锁定胜利，返回前不进入清手或切换敌方。独立原生宿主在进入 `card_reward` 时读取终局战斗续体戳，保留当前玩家窗口。顺序可在本地 `logs/iih8-turn.il` 的 `EndPlayerTurnPhaseOneInternal` 指令中核对，`DoTurnEnd`、胜负检查和 `BeforeFlush` 分别在 `0574`、`06e9`、`079b`。

预测的 `SimulateEndPlayerTurnAfterOrbPassives` 在球体致胜后看到 `IsOverOrEnding` 就提前返回，跳过胜负锁定。外层随后切入敌方，直到敌方回合开始检查才停止。续体序列化由此读取了敌方窗口的零计数。pair16 当回合的 Cold Snap 与 Ball Lightning 均为攻击，故还少了两次 `AttackStarts`。holdout 的 Zap 与 Tempest 均为技能，仅 `Y` 不同。

修复移除这一处提前返回。`DoTurnEnd` 仍自行跳过结束中的工作，外层保留原有第一阶段胜负检查与尾部补偿，锁定后在切边前停止。两根复验确认共同根因。E3 戳序列化与严格认证合同沿用原实现。

## 定向验收

| 检查 | 结果 | 耗时 |
| --- | --- | ---: |
| iik.1 冻结复放 | pair16 `0:000006` 和 holdout `1:000010` 均在索引 15 复现原差异，原生 `Y=0/0/2/2`，预测 `Y=0/0/0/0`。pair16 的 `AttackStarts` 原生 2、预测 0 | 9.2／5.1 秒 |
| 最小原生夹具 | 夹具牌组为三张 Zap+ 和两张 Defend。非致胜的 22 次回合结束两版均精确；最后敌人剩 1 HP，打出两张 Defend 后由闪电球被动致胜。基线重现 `Y` 差异，候选终局戳精确 | 4.0／5.6 秒 |
| 候选冻结复放 | 两根各 16 个决策与 16 个稳定原生边界，均在索引 15 精确获胜 | 4.9／5.3 秒 |
| 固定策略同根重采 | 两根各一次，原模型和种子、128 动作预算、关闭优化。两根均保留全部 16 个历史决策记录，取得 `admissible_predicted_win / exact_native_match`，终局戳分别与候选冻结复放一致 | 根内 8.8／8.4 秒，串行总墙钟 28.1 秒 |

同根行为种子依次为 `17756356810165692696` 与 `7830050736440340670`。候选编译一次，编译器计时 44.69 秒，出现一条 CS9124 警告。测试耗时单独列出。

## 关联见证

| holdout 根 | 原首差仍存在 | 耗时 |
| --- | --- | ---: |
| `1:000020` | 索引 17，Lightning Rod 原生 2 层、预测 1 层 | 5.1 秒 |
| `1:000021` | 索引 20，末两枚 Glass Orb 原生 `2/4,3/6`，预测 `3/6,4/8` | 5.1 秒 |
| `0:000023` | 索引 9，敌方 Strength 原生 15 层、预测 18 层 | 5.3 秒 |

三个关联见证的首差字段和数值均与 II-J.5B 证据一致，均止于原首差复放。

## 复现

从仓库根执行，使用新的输出前缀。每条命令的详细输出可重定向至独立日志。冻结路线与重采均从 `logs/iij5b-serial-{pair16,holdout}/training.sqlite` 只读提取指定根。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$h = 'experiments/m1-nosl3c-iik21'
$r = 'logs/new-iik21'
python "$h/verify_routes.py" "$r-before" logs/iik1-solver
python "$h/verify_orbs.py" "$r-fixture-before" logs/iik1-solver
python "$h/build_solver.py" "$r-solver"
python "$h/verify_orbs.py" "$r-fixture-after" "$r-solver"
python "$h/verify_routes.py" "$r-after" "$r-solver"
python "$h/verify_routes.py" "$r-related" "$r-solver" --related
python "$h/resample_roots.py" "$r-resample" "$r-solver"
```
