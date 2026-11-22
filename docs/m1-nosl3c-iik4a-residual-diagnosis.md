# II-K.4A — 原生超时与动作预算耗尽

起点 `port/v0.113.1@51c3dbc`。使用现有候选 `0.51.5-iik.3b` 和 II-H.7 战斗宿主。原账本按套件、步和根只读查询。所有运行串行，保留首次输出。本轮仅诊断，正式全量验收基线为 `0.51.5-iij.4`。

## A. pair16 0:000001 原生回合超时

Regent 对 Inklets，根种子 `1945C6BDD1A9F924`，原行为种子 `10494285998192343072`。II-J.5B 账本保留 37 个预测胜局决策。审计报告 `audit_failure`、`terminal_verified=false`。原生宿主首错在 `logs/iij5b-serial-pair16/engine/game-8i06m9c_/stderr.log:104`。

唯一一次 iik.3b 冻结双进程复放重现同一错误。第 12 回合索引 32 打出 Rolling Boulder，索引 33 打出 Stardust。索引 **34** 提交 `end_turn` 时玩家 839 HP、0 格挡，两只 Inklet 剩 3 和 12 HP。敌方回合执行后原生推进到第 13 回合 `Start`，玩家 830 HP，战斗仍在进行，动作执行器已停止。后续索引 35、36 未获原生执行。

首个异常是 `RollingBoulderPower.AfterPlayerTurnStart` 在 JIT 时找不到 `Godot.Error Godot.GodotObject.Connect(Godot.StringName, Godot.Callable, UInt32)`。调用由 `Hook.AfterPlayerTurnStart` 经 `CombatManager.SetupPlayerTurn` 进入，异常让原生回合循环退出。当前仓库的 `src/GodotStubs/Core.cs` 定义了 `GodotObject`，`src/GodotStubs/UI.cs:53` 的两参数 `void Connect` 属于 UI 类型，无法满足此调用的声明类型及签名。

宿主 `DoEndTurn` 泵送同步上下文，在 5 秒内等待下一回合已开始且进入 `Play`，或战斗结束、玩家死亡、出现选择。循环退出后这些条件均未成立，返回 `combat_turn_timeout`。原生回合任务已经异常退出，故等待阈值和交互恢复均无法解决此首错。该见证仍为宿主兼容性失败，终局未认证。复放证据在 `logs/iik4a-a.log`、`logs/iik4a-a/commands.json` 和 `logs/iik4a-a/engine/game-mh_pt2f4/{stderr,stdout}.log`。

## B. holdout 1:000029 动作预算

Regent 对 Axebot，根种子 `4591801DD2503F4C`，原行为种子 `8272045754352118500`。原模型来自相同训练步的 SQLite 快照，SHA-256 为 `cb2130276dd73a62703a8a0b955b92809fdd7db3b23f8e10719f73d40a4006a9`。两次重采均关闭优化。

原路线和两次重采中，Axebot 始终为 70 HP。牌组没有攻击或伤害来源，Constellation 只能选另一玩家，在单人路线从未出现在合法动作中。主要序列为反复用 Particle Wall 获得格挡，用 Venerate、Glow、Genesis 补充星星或抽牌，再结束回合。玩家 HP 随敌击下降，公开状态仍在推进。重复的是防御与资源模式，现有证据支持牌组与策略缺少推进胜利的手段。

| 预算 | 实际结果 | 末记录 | 认证 | 耗时 |
| --- | --- | --- | --- | --- |
| 128 | `truncated / action_cap`，129 条归档记录含末尾未推进的预算标记，与原归档逐条一致 | 第 31 回合，799 HP、45 格挡，敌人 70 HP。Particle Wall 59 次 | 0 原生边界，未认证 | 根内 3.9 秒，命令墙钟 7.5 秒 |
| 256 诊断 | `truncated / action_cap`，257 条记录含末尾标记，前 128 个有效决策一致 | 第 64 回合，557 HP、9 格挡，敌人 70 HP。Particle Wall 118 次 | 0 原生边界，未认证 | 根内 4.9 秒，命令墙钟 8.7 秒 |

两项输出分别保存在 `logs/iik4a-b128/1-000029.json` 和 `logs/iik4a-b256/1-000029.json`。256 仅供诊断，未计入固定套件认证数。

## 阶段建议

建议先做 **II-K.4B 宿主兼容性修复**，验证 Rolling Boulder 回合开始路径所需的 Godot ABI 与信号行为，随后用同一超时阈值复放该根并尝试原预算下的严格认证。Axebot 见证继续按 128 动作预算记录为策略截断，无需 Solver 或准入修复。宿主见证处理后即可进入最终累计验收。
