# M1-D2A 两条自然跑局的原生选牌支持

2026-11-18。基线 `80cf4af843a2542ebb3020e56f429ddb35468da6`，STS2 v0.113.1 / Build 26660232，Windows x64 / CoreCLR 9.0.7。D1 正式批次的两条受阻局史均越过原回调，按原路线继续到实际死亡。共新增一个严格恢复的第一幕精英战根。

## 阻塞与最小原生证明

| D1 自然局史 | 首次中止位置 | 实际原生请求 | 修复后的原生实例效果 |
| --- | --- | --- | --- |
| `silent-3`（静默猎手 A0，`run_3`） | 第一幕第 7 层 `BYRDONIS_ELITE`，第 2 回合第 6 步，涅奥之怒 `NEOWS_FURY` | 9 个弃牌堆实例，允许选择 0–2 张。首个回调即被拒绝 | 选项 `[8,0]` 对应生存者和候选中的第一张防御。两张原实例离开弃牌堆并进入手牌，升级等级保持 |
| `iron-4`（铁甲战士 A0，`run_4`） | 第一幕第 8 层 `INKLETS_NORMAL`，第 2 回合第 5 步，武装 `ARMAMENTS` | 4 个可升级手牌实例，必须选择 1 张。首个回调即被拒绝 | 选项 `[1]` 对应两张防御中的第一张。原实例留在手牌，升级等级从 0 变为 1，其余候选的升级等级保持 |

基线选择器收到首个请求时找不到这两个卡牌 ID 的合同，直接返回 `unknown_or_repeated_request`。判断在校验候选实例与处理选择续体之前发生。两个合法地图检查点分别只需执行进场后 6 步和 5 步即可复现。使用旧宿主的原生 `play_card` 独立执行同一张牌，会得到 `card_select`，完整候选顺序及选择上下限与新选择器一致。手动提交相同索引后，两个请求都恢复到 `combat_play`。

修复后的自动选择与手动路径逐项匹配完整公开状态、含 RNG 的 live 延续摘要和四项 RNG 计数。涅奥之怒的选择前后计数均为 shuffle/generation/selection/monster_ai = 10/0/0/1，武装为 11/0/0/7。选择后 live 摘要分别为 `914e8b830d17a251c6c21bdcc9cc6a4e5ae8d4ae07ad1052cd77d0eecd27020c` 和 `dd07148305a1d1dd4ec5a91c5d9ebb27b663ef163078c66b67ed51badf811c6a`。

## 修改范围与跑局结果

新增隔离宿主 `m1-d2a-build`，复用 F2/F3A 的原生选择作用域、事务生命周期、候选实例验证和 RNG 审计。涅奥之怒从符合原生选择上限的候选中按现有公开选牌价值排序，跳过状态和诅咒，最多选取原生允许的张数。未升级的武装按相同价值排序，只绑定一张原生可升级手牌。F1/Q1 的出牌决策源码、原有选牌合同、F3B 搜索代码、正式引擎入口和 D1 数据格式均保持原样。

| 局史 | 共同前缀命令 | 修复前 | 修复后 | 严格根 |
| --- | ---: | --- | --- | --- |
| `silent-3` | 73 | 第 7 层中止，累计 74 条命令 | 第 7 层原生死亡，累计 101 条命令 | 4 → 4 |
| `iron-4` | 78 | 第 8 层中止，累计 79 条命令 | 清完第 8 层，推进到第 12 层并正常死亡，累计 132 条命令 | 5 → 6 |

共同前缀从同一种子起局，在旧、新宿主中逐命令复放。对比完整公开响应、原生地图、每个战斗入口的 live 身份和资源、每个活动战斗步骤的前后摘要与 RNG，151 条全部相等。静默猎手前缀中原有生存者弃牌的实例和选择记录相等。首个差异是目标回调从拒绝变为完成，触发该回调的出牌动作相等。

D1 入口原样采样，10/10 个候选通过独立冷恢复，两局仍归 validation。原有 9 根的公开开局、live 身份及地图摘要相等。唯一新增的 L0 根是铁甲战士第 12 层的 `BYGONE_EFFIGY_ELITE`，入场 80 HP，live 摘要为 `4525501939d5d01b3f24d55db7594414c7a4dddfe4084740e0860cd6dc6eef88`。两局均未到第二幕。

## 回归、工作耗时与 D2B 接口

新增 5 项定向回归全部通过，含两条最小夹具、两条从起局开始的前缀差分和一项 D1 清单验收。隔离构建 0 错误、7 条既有 GodotStubs 警告。Python 编译、D1 Schema 校验和 Git diff 检查通过。验收范围为新增隔离宿主和这两条自然局史，本次未运行全量 pytest、五角色批次或完整 D1 正式批次。

| 环节 | 实测墙钟 |
| --- | ---: |
| 调查，自首次基线探针启动到最小证据落盘 | 约 28.4 秒 |
| 合同设计及修改，自最小证据落盘到首版写完 | 约 81.0 秒 |
| 隔离 SDK 构建 | 8.57 秒 |
| 两条局史通过数据工厂重跑并完成冷审计 | 14.99 秒 |
| 五项定向回归 | 33.13 秒，其中两项最小夹具用时 18.07 秒 |

其他卡牌和嵌套选择留在既有支持范围。未覆盖涅奥之怒遇到手牌容量或其他触发器改变目的牌区的情形。该补丁核对回调结算后活动战斗中的实际目的牌区，未满足合同的请求仍会以结构化原因中止。武装升级版按原生自动结算路径执行，本次夹具覆盖的是未升级版的显式选择。

D2B 可用 `bank.py sample --host m1-d2a-build` 搭配 D1 格式配置，在新目录采集。选择证据继续通过 `f1_step` 的 `choice_requests` 和 `choice_checks` 读取。旧 bank 保有原来固定的引擎哈希。跨宿主比对用局史、地图摘要、公开开局和原生 live 身份，严格根 ID 还会纳入宿主版本。

## 复现

从仓库根执行。使用 [项目环境](PROJECT_STATUS.md) 中的本地游戏 DLL、固定 CombatSolver、CoreCLR 9.0.7 和 pytest。已有 D1 正式清单可以直接作为基线。若需要重新生成基线，仅运行以下两种子配置。

```powershell
python -X utf8 experiments/m1-f3b/build.py
python -X utf8 experiments/m1-d1/bank.py sample logs/d2a-baseline --config experiments/m1-d2a/cases.json --host m1-f3b-build --workers 2
$env:STS2_D2A_BASELINE = (Resolve-Path logs/d2a-baseline).Path
python -X utf8 experiments/m1-d2a/build.py
python -X utf8 experiments/m1-d1/bank.py sample logs/d2a-reruns --config experiments/m1-d2a/cases.json --host m1-d2a-build --workers 2
$env:STS2_D2A_RERUNS = (Resolve-Path logs/d2a-reruns).Path
python -X utf8 -m pytest experiments/m1-d2a/test_native_choices.py -q -s --durations=0
```
