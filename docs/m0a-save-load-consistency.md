# M0-A 存档恢复与分支一致性

## 基线与范围

仓库 matrix773768/sts2-cli，远端目标分支 test/save-load-consistency。
本次开始时工作区干净，HEAD 与 git ls-remote 得到的目标分支提交均为
fec723a21741a1a33a4f54dc9b28c50df31d6e45。获取远端引用后建立同名本地分支，未改动 main，未推送、合并或创建 PR。

原有两个测试只验证 map_select 不重新触发 Neow、开局存档仍保留 event_choice，无法证明玩家资源、地图位置或后续 RNG 消费一致。
LoadSave 会反序列化 SerializableRun，启动 RunManager，必要时 EnterAct，再恢复访问坐标和楼层；这些操作可能影响 RNG 或状态。SaveCheckpoint 在非地图房间会回退至进房前，因此测试只使用真正的地图检查点。

字段依据 RunSimulator.cs 的 PlayerSummary、战斗决策、地图决策与 GetFullMap 实现确认：玩家包含 hp/max_hp、gold、deck、potions、relics；战斗包含 hand、enemies、intents 等；地图包含 current_coord。当前无 DLL，未获取真实运行样本。测试不猜测存档 JSON 内部字段，运行时验证响应类型，完整比较状态及地图 JSON，包括新增字段、缺失字段和数组顺序。

## 改动

- tests/test_save_load.py：增加连续运行与加载重放测试；增加独立进程 A/B/A 分支测试；为本文件四个真实游戏测试添加缺少 lib/sts2.dll 时的明确跳过原因。DLL 存在时启动或运行失败仍然失败。
- tests/save_load_support.py：递归首次差异报告，以及依据 can_play、能量和存活敌人选择的简单战斗策略。
- tests/test_save_load_support.py：无引擎单元测试，验证嵌套字段、字段缺失、新字段、数组顺序、长度、类型差异、动作选择，以及重放首次失败步骤与进程清理。
- 本文档：记录复现方法、验证结果和覆盖边界。

连续路径从固定种子 m0-a-save-load-1 的 Neow 后地图存档出发，记录合法 Monster 节点动作及逐个战斗动作，直到首个非战斗决策。新进程加载后执行完全相同命令，在每一步比较完整状态与完整地图；首个房间的敌人、抽牌、意图和奖励等随机结果均纳入比较。要求实际执行多个战斗动作，300 步未结束则失败。

分支路径要求起始地图至少有两个不同合法节点，依次在独立进程运行 A、B，再在第三个独立进程重放 A。每个分支均从同一个源文件加载，比较初始状态；每轮及最终逐字节检查源文件未变。不同分支不要求结果相同。非战斗分支只运行至房间入口，不自动选择事件或消费奖励。

## 本环境验证

pytest 原先未安装，本次只将 pytest 及依赖下载到 /tmp/sts2-m0a-pytest，未修改项目依赖或环境配置。

执行：

```bash
PYTHONPATH=/tmp/sts2-m0a-pytest python -m pytest -q \
  tests/test_save_load_support.py tests/test_save_load.py \
  tests/test_setup_tools.py tests/test_play.py \
  -k 'not interactive_launcher_without_steam_fallback and not test_setup_repairs_missing_module_dependency'
python -m compileall -q tests
git diff --check
```

结果：19 passed、4 skipped、6 deselected；语法编译和差异空白检查通过。
4 个跳过项是本文件原有两个及新增两个真实游戏测试，均未运行。5 个真实游戏启动参数用例被排除。另一个被排除的原有 test_setup_repairs_missing_module_dependency 曾实际运行失败：play.ensure_setup 在缺少 .NET SDK 时提前 SystemExit(1)，未到达该测试预期的依赖修复逻辑。未修改该测试，也不将其报告为通过。
pytest 输出另有环境已有 anyio 插件关于 pytest 10 的弃用警告。

## 具备游戏文件时执行

先按仓库 README 用已有的合法游戏文件完成 setup.sh 和 .NET 9+ 构建，使 lib/sts2.dll 及其依赖、构建产物可用。本次没有运行 setup.sh 或修改环境配置。随后在仓库根目录运行：

```bash
python -m pytest -q -rs tests/test_save_load.py tests/test_save_load_support.py
# 完整项目测试
python -m pytest -q tests
```

前一命令应执行全部 13 项（9 项单元、4 项游戏集成）；确认没有因缺少 DLL 而跳过。CI/外层运行器宜设置进程级超时：现有 Game 使用阻塞读取且 stderr 未持续排空，异常引擎可能导致挂起。

## 风险与下一步

固定种子在实际目标游戏版本是否提供 Monster 和两个合法初始节点尚未验证；条件不满足会明确失败，不会换种子重试或降低断言。先在真实环境运行并检查首次差异，再判断引擎恢复问题、版本变化或测试前置条件。

测试只证明所选路径上的可观察行为；不读取内部 RNG 状态、不涵盖整局、多幕、所有角色、非地图存档或任意中途房间恢复。玩家初始药水等字段可能为空，虽完整比较，但不足以覆盖非空资源恢复。建议下一步添加真实可复现的中期地图存档（非空药水、升级牌、额外遗物、已访问路径），并扩展至多个房间及奖励消费后的地图检查点。
