# M1-CORE-2　机制化 C 战略状态与学习接口

研究起点 `1816e757104a6072ba0976cb48d50385053ea7af`。沿用 CORE-1R2 的抽牌前 C 接点、公开多重集信念、战术见证和开发族划分。24 个开发族、18 个遭遇在一个固定公开续策下实际执行 712 步，产生 131 个 C 和 24 份终局账本。10 胜、14 死反映该续策的采集分布。131 个样本共享 24 场终局，划分和不确定性估计应以构筑族或整场为单位。[逐场记录](../experiments/m1-core2/evidence/records.jsonl.gz) · [验收摘要](../experiments/m1-core2/evidence/summary.json)

## 表示与规则

在原有宿主的隔离构建上扩展观察器。公开时点、动作、抽牌和敌方执行均沿用原引擎。新版 C 保留 HP、持续资源、Power、攻击逐段、当前节点、已执行节点、物种寄存器、牌区、已知顶底、待抽张数及 setup 进度。可见牌实例增加按原生应用顺序排列的能量／星费修改层，记录操作、到期条件和仅降费标志。C 的药水槽从当前模拟状态逐槽读取。可读取的遗物增加 Iron Club、Joss Paper、Happy Flower 等已有计数器和 Meat on the Bone 的 HP 条件；实际阈值对照使用双节棍。[导出接点](../experiments/m1-core2/build_state.py)

静态规则按物种、Power 和遗物 ID 缓存。复用 N1A 的原始机制导出，在 N1BC 与 CORE-1R2 已有拓扑上恢复每个具名行动的基础攻击段、效果（含目标 Power 与数值）、条件边、冷却及重复限制。开发 C 出现的玩家 Power 另用同一导出器提取钩子。合计 53 个敌人图、45 种 Power、1 份遗物静态规则；卡牌操作继续引用冻结目录。消费者通过当前节点和具名后继读取完整图。例如 Mawler 的 Roar 会向目标施加 3 层易伤，影响后续压力，即使该行动本身没有攻击段。[规则目录](../experiments/m1-core2/catalog.json.gz)

动态上，对每个分支的每条候选边调用与宿主一致的历史重复／冷却检查，并导出目标、规则、窗口参数与通过标志。39 个当前节点的直接后继具有这种窗口，19 个窗口缩小了静态候选集合。30 组可对照的同一敌人连续 C 中，下一次实际公开行动全部在允许集合中。死亡、缺少下一 C 或无对应分支的样本没有进入分母。通过窗口的多条边仍可能需要其他条件；没有给它们分配意图概率。合同区分多个合法候选、未知条件和已经确定的转移。

## 战略可辨性

| 公开对照 | 规则执行结果 |
| --- | --- |
| 当前攻击相同 | 同一开发族同一敌人槽，连续两次显示单段 11。Acid Goop 之后实际为单段 11 的 First Acid Goop；First Acid Goop 之后为无攻击的 Inhale。节点、具名边和下一 C 均可核对。 |
| 当前力量相同，启动机制不同 | Inflame+ 后三个 C 的力量为 3、3、3；Demon Form 后为 0、3、6。第二个 C 双方 HP 76、力量 3，公开成长 Power 区分第三个 C 的结果。 |
| 当前费用相同，清理结果不同 | 在隔离模拟器内给两张基础牌都施加回合内 0 费，其中一张有更早的战斗内 2 费层。显费均为 0，实际调用原生回合清理后分别为 2 和 1。此项为生命周期单元干预，其余下列出牌均经合法菜单。 |
| 同牌组，关键牌位置不同 | Strike 后接 Headbutt，把刚弃掉的 Strike 放回牌顶。C 中记录已知顶牌，随后 B 第一张实际抽到 Strike。仅出 Strike 的对照在同一 C 没有已知顶牌。 |
| 减力量与跨回合资源 | Mangle 使当前攻击从 4 降至 0，第一个 C 的 HP 为 80，对照为 76。第三个 C 临时效果已过，仍保留 69 对 65 的 HP 差。 |
| 阈值遗物 | 同一 Strike 在无遗物时余 2 能量，双节棍计数 9 时余 3，实况推进到下一 C。 |

规则对照没有使用人工价值标签。六项测试核对实际执行值、标签来源、分支质量和原生终局。[机制轨迹](../experiments/m1-core2/evidence/diagnostics.json.gz) · [测试](../experiments/m1-core2/test_state.py)

## CORE-3 可以使用的数据

- `learning_batches(path, size)` 提供真实执行的 C、截至该 C 的公开动作历史、构筑族、续策 ID 和单独的终局目标。目标含胜负、HP、最大 HP、金币、药水槽及从 C 到终局的带符号净战损。所有 131 个 C 都到达终局。续策为固定公开菜单顺序，选择时优先确认待选，否则取首个合法项。前两个预定开发族按原动作分别在原生执行 27 和 24 步，一胜一死，终局资源一致。主数据仍为 prediction_only；药水变化未在这个空槽面板中实测。[原生复核](../experiments/m1-core2/evidence/native.json)
- `strict_batches(size)` 对接旧面板的独立严格重放，提供根、公开前缀、已选条件策略、逐叶见证及条件质量。56 次查询中，严格 C 质量合计 47，缺敌方条件的质量合计 9。旧 C 缺费用层时保留版本标记。反事实默认没有终局标签和续策身份，取得定义明确的实际续战后才能加入有监督终局目标。
- `policy_batches(path,size)` 读取带代理和其他停车原因的诊断分布。每个策略单独守恒；代理显式标为 `C_model`，不具备严格教师资格。接口不限制根候选数。历史搜索器即时评分最多留三条的做法仍限制可比较的候选多样性，留给 CORE-3 检验。[批量接口](../experiments/m1-core2/core2_dataset.py)

编码采用按实例、敌人、效果和有序费用层组织的变长记录。只把当前知识送给评价器；读取整场轨迹的代码把未来终局留在目标侧。131 个自然 C 的机制联接耗时 12.6 ms，紧凑 JSON 中位 4,703 字节；计时不含宿主推进、模块导入或神经网络。确认集和冻结 G2 均保持原状。

**资格范围。** 隐藏牌堆只有公开多重集及位置约束，无法绑定到公开实例的费用载荷单独标缺；Power 钩子未完全展开，更多遗物、跨阶段选择和个别敌人条件仍缺。临界计数以外的新增遗物分支尚缺原生逐项验证。CORE-2 满足首批开发域机制表示与真实标签接入要求；代理反事实的长期价值、搜索教师收益与跨构筑泛化均待 CORE-3 验证。

## 复现与计算

从仓库根运行。归档读取和测试使用已提交证据。重新构建沿用 CORE-1R2 的游戏、Workshop、N4B 和 SV4A 构建依赖；静态目录的原始输入来自 N1BC 和 CORE-1R2 的机制导出目录。使用新的日志目录防止覆盖历史数据。构建试错、两次完整面板、两批成功机制复验和原生复核均进入计算账本。训练更新及 GPU 计算为零。[分项计算账本](../experiments/m1-core2/ledger.json)

```powershell
python experiments/m1-core2/build_state.py logs/new-core2-build
python experiments/m1-core2/collect.py logs/new-core2-panel logs/new-core2-build
python experiments/m1-core2/diagnose.py logs/new-core2-diagnostics logs/new-core2-build
python experiments/m1-core2/native_audit.py logs/new-core2-native logs/new-core2-panel/records.jsonl.gz
python experiments/m1-core2/measure.py logs/new-core2-panel
python -m unittest discover -s experiments/m1-core2 -p test_state.py -v
```
