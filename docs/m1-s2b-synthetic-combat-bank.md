# M1-S2B 批量原生合成战斗数据工厂

基线 `0e7d3a09d412c5cb1e0e3565072a0861e9625f69`。环境为 STS2 v0.113.1 / Build 26660232、CoreCLR 9.0.7、冻结 CombatSolver 0.51.5。正式批次 **256/256** 个根通过独立原生重建，共 512 次冷进程初始化，失败、超时及严格重复均为 0。每个根记录 `synthetic=true`、`native_reachable=unknown`。结果证明配置可用原生引擎重现，真实跑局可达性仍未知。

## 生成与划分

用 S2A 的 ModelDb 校验角色卡池、可升级性、普通遭遇所在幕变体及药水，以固定 seed 生成配置。正式批次使用 8 个模板和 8 个遭遇，每个模板与遭遇组合有 4 个实例，两种资源档位各 2 个独立 seed。新增四类模板为易伤群攻、扣血力量、敏捷格挡和开场爆发。正式计划预检发现共享选牌池可能提前耗尽，此后生成时按剩余攻击与防御槽检查两池及其并集容量，优先保留原随机选择，在会耗尽卡池时选一个仍可完成卡组的合法选项。试批的原配置保持逐项一致。旧 S2A 单实例生成路径沿用原规则。

| 覆盖维度 | 已验证数量 |
| --- | --- |
| 角色 | 铁甲战士 128，静默猎手 128，均为 A0 |
| 幕 | 第一幕 160，第二幕 96 |
| 卡组模板 | 力量多段、格挡转伤、中毒、小刀成长、易伤群攻、扣血力量、敏捷格挡、开场爆发各 32 |
| HP 资源档 | `early` 70–88%、`lean` 40–55%、`hive-low` 45–65%、`hive-stocked` 78–100%，各 64。档位名沿用 S2A，实际幕由遭遇决定 |
| 集合 | development 128，validation 64，test 64 |

每种遭遇各 32 根。同一个遭遇的全部角色、模板、资源和 seed 共用一个集合。开发集使用 `SHRINKER_BEETLE_WEAK`、`NIBBITS_WEAK`、`CORPSE_SLUGS_WEAK`、`BOWLBUGS_WEAK`。验证集使用 `FUZZY_WURM_CRAWLER_WEAK` 和 `EXOSKELETONS_WEAK`。测试集使用 `SLUDGE_SPINNER_WEAK` 和 `THIEVING_HOPPER_WEAK`。后两组四种遭遇均未进入 S2A 原计划。划分和两条开发、两条测试抽评名单由版本化配置固定，在标注前写入 `plan.json`。同类卡组模板可在不同遭遇出现，所得对照衡量跨遭遇表现。试批使用独立的种子空间，只有开发根运行了标注。

## 存储、恢复与资源

`plan.json` 固定配置、catalog 和二进制哈希、生成 seed、模板、参数、集合及完整 Spec。`roots/<case-id>.json.gz` 按样本原子发布，包含内容哈希、原生快照、完整公开状态、资源、两个重建记录和失败说明。完整原生 RNG 和 continuation 参加两次冷建比较。落盘前按 Spec 摘要及完整原生 live 身份去重。损坏内容或版本漂移会阻断校验，整批中断后重跑会继续处理未完成样本。已有计划只允许在同一配置下追加实例。原生进程使用隔离临时目录，正式批次未发现真实存档或原生战斗回放文件。

四个 worker 实测 192.92 秒生成 256 个严格根，即 **79.62 根/分钟**。并行冷建累计 675.79 秒，其中启动 82.32 秒、原生初始化 552.47 秒、状态读取及构造 41.00 秒。并发原生进程同时工作集峰值 361.8 MiB，最大单进程峰值约 96.0 MiB。标注前落盘约 1.92 MiB。资源限制默认约束 900 MiB 进程工作集、512 MiB 工作目录、每个样本 100 秒及批次 900 秒。工作集为 20 ms 采样，磁盘在调度和发布时检查，临时进程输出可能在检查间隔内短暂超限。批次触及边界时取消未发布工作，已落盘根可续跑。试批在 15 秒时限后保留 16 根，继续运行完成另外 16 根，原有 16 个归档的文件 SHA-256 全部相同。

## 搜索标注与对照

使用冻结 F3B C 和 F4，统一 512 次计费预测转移、禁用主动药水。F4 复用同根同预算的 F3B 首条严格胜路。在支持的原生 Neutralize 兼容路径中，沿用 F3D-B 的定向补丁撤除及完整根校验。实验证据保存原始预测轨迹、候选动作和每步状态、独立固定帧、原生重放、终局资源及失败原因。重放使用冷进程，并逐帧比较完整状态、RNG 和 continuation。标签均标记 `offline_oracle=true` 和 `uses_hidden_rng=true`。标签按根、算法、预算、版本和实现摘要追加。只有完整严格原生胜路晋级 L3，预测胜路停留 L2，未发现胜路的根保留 L0，获胜可行性记为未知。

下表为原生结算后 HP 和总计费。两种算法各验证 3/4 个抽评根，其中开发集 2/2、测试集 1/2。所有已验收路线主动药水消耗为 0。

| 集合 | 固定抽评模板／遭遇 | F3B 等级／HP／转移 | F4 等级／HP／转移 |
| --- | --- | --- | --- |
| development | block／`SHRINKER_BEETLE_WEAK` | L3／39／22 | L3／39／207 |
| development | shiv／`BOWLBUGS_WEAK` | L3／20／64 | L3／20／464 |
| test | strength／`SLUDGE_SPINNER_WEAK` | L3／41／46 | L3／**50**／236 |
| test | poison／`THIEVING_HOPPER_WEAK` | L2／未知／213 | L2／未知／213 |

`SLUDGE_SPINNER_WEAK` 的 F3B 初始候选在第 10 步出现严格差分，重试的保底路线 8/8 步匹配。F4 的三个送审候选均获原生验收，选中路线 11/11 步匹配。原生战损减少 9，药水栏保持一致。`THIEVING_HOPPER_WEAK` 的三个预测胜路在独立固定帧阶段均遇到 `InvalidOperationException: Sequence contains no matching element`，未进入原生胜路验收。F4 记录同一未决结果，获胜可行性仍为未知。四根规模只能说明接口可用及本次观察到的资源变化。

正式标注耗时 80.80 秒，峰值工作集约 128.8 MiB，标注后目录约 2.10 MiB。隔离宿主构建 9.39 秒，0 错误、7 条既有警告。19 项定向回归通过（2.35 秒），覆盖 S2B 冻结计划、追加合同、续跑字节一致性、计费和原生证据，同时复核 S2A、F3D-B 与 F4。未运行全量 pytest 和五角色批次。

## 复现

```powershell
python -X utf8 experiments/m1-f4/build.py
python -X utf8 experiments/m1-s2b/factory.py generate logs/m1-s2b/pilot --cohort pilot --workers 4
python -X utf8 experiments/m1-s2b/factory.py label logs/m1-s2b/pilot
python -X utf8 experiments/m1-s2b/factory.py generate logs/m1-s2b/formal --workers 4
python -X utf8 experiments/m1-s2b/factory.py label logs/m1-s2b/formal
python -X utf8 experiments/m1-s2b/factory.py verify logs/m1-s2b/formal
python -X utf8 -m pytest experiments/m1-s2b/test_factory.py -q --basetemp logs/m1-s2b/pytest-repro
```

定向回归的续跑断言读取本次实测前缀摘要，普通复现缺少该文件时仅跳过这项断言。生成计划重现用例读取 S2A 留存的 ModelDb catalog。默认标注冻结名单中的根。要追加指定根或预算，使用 `label <目录> --root <case-id> --budget 128 --algorithm f3b` 或 `--algorithm f4`。根归档保持原样。中断后以同一目录及配置重跑生成。追加实例时使用 `generate <目录> --replicas 5 --extend`。原生完整归档与标签留在本地 `logs/m1-s2b`。仓库保留[生成配置](../experiments/m1-s2b/config.json)、[数据合同](../experiments/m1-s2b/bank.schema.json)、[256 根实测索引](../experiments/m1-s2b/index.json)和[计时及标签摘要](../experiments/m1-s2b/results.json)。
