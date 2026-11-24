# M1-DC2B 实施与验收协议

基准提交为 `82d43213bfa00aa9741a9f2e9eece0f57c9f06ea`。使用 v0.113.1、Solver 0.51.5-iik.3b、单人 Ironclad NOSL、prediction_only。固定历史能力开发队列继续使用 DC1 development。新增复杂构筑开发和确认配方独立冻结。正式任务只执行开发评估，确认另行批准。

## 冻结与运行

也可在 [INF2 本地训练中心](inf2-training-dashboard.md) 审核、冻结和提交这两项任务。

从仓库根运行。项目负责人先复核配置再冻结和提交。

```powershell
$inf1 = '.\tools\training_manager\inf1.ps1'
python -X utf8 experiments/m1-dc2b/stages.py freeze logs/m1-dc2b-frozen
& $inf1 freeze configs/training_jobs/dc2b-initial.json logs/inf1/dc2b-initial.frozen.json
& $inf1 submit logs/inf1/dc2b-initial.frozen.json
& $inf1 start
& $inf1 mode Full
& $inf1 status dc2b-initial
& $inf1 report dc2b-initial
```

初始任务成功且 gate 通过后，以相同命令冻结及提交 `configs/training_jobs/dc2b-curriculum.json`，任务 ID 为 `dc2b-curriculum`。暂停和恢复分别使用 `& $inf1 pause dc2b-curriculum` 和 `& $inf1 resume dc2b-curriculum`。用 `report` 查看阶段目录、日志和运行预算。Full 与 Idle 可运行，Light 等待重 CPU 和 CUDA 阶段。已启动管理器时可直接提交新任务。

初始化预算为 4,096 次更新，每批 512 条，最多 6 小时运行时间。原 DC1 开发队列 512 场与冻结 D2 配对。胜率下降超过 5 个百分点、死亡率上升超过 5 个百分点或共同完整低于 98% 时，任务在门槛阶段失败。

课程最多三代。每代目标 8,000 条直接 Q、2,000 条搜索完整经验，尝试上限分别 8,704 与 2,176。生产以事务批为边界，最后一批可超过目标，最多达尝试上限。每代 1,600 次更新，每批 512 条，累计最多 24 小时。至少半批从当代及此前课程经验抽样，其余从合并池抽样。冻结行为身份与模型在各代分开登记。训练以最多 64 次更新及验证后的原子检查点恢复。战斗在已提交批次后响应停止，缓存阶段从头重跑。阶段不自动打开确认集。
