# INF1 实现与验收

## 工程调查

起点为 `port/v0.113.1` 的 `27e3cd9f96081ec740fa0a8fde5ecd2b3c4e8f3c`。

| 入口 | 恢复与进度合同 |
| --- | --- |
| SV4A `campaign.py` 和 `stages.py` | 可独立启动。祖先、冻结根、预检选择、阶段产物和继续训练身份均有持久化检查。默认双路含确认阶段。训练子进程退出失败会使当前工作流失败。 |
| SV4A `loop_battle.run` | 通过 PRE0B 同类传输启用常驻预测宿主，每个 Worker 独立使用 Lane，多根后回收。Worker 池以最多 `workers × 4` 提交一批，SQLite 逐根提交，ordinal 主键去重，冻结合同锁定代码、参数和输入。异常退出释放 writer 锁，后续启动仅调度未提交根。可用 `max_new` 缩小调用边界，保留历史合同。 |
| DC1 `dc_produce.py` | 从冻结训练族及家族分析按轮次生成新世界，校验已发布策略及参数，调用同一战斗账本。原 CLI 从一个输出目录找输入及写产物，INF1 分别传入只读参考与新输出目录。 |
| SV3A `sv_data.py` 和 SV4A `loop_learn.prepare` | 特征分片原子替换，训练时核对 SHA-256。正式 SV4A 特征入口有正式样本规模准入门槛。INF1 的新分片适配器复用同一个编码和分片实现，适用于较小的已批准有限队列。 |
| SV3A `sv_train.train_arm` 和 SV4A `loop_learn.fit` | 完成 epoch 时保存模型、AdamW、调度器、随机状态和更新计数，使用原子替换。`until` 可限定完成的 epoch。INF1 在每个 epoch 后发出真实进度并检查暂停。原有源文件与正式权重保持原样。 |

调度状态存在 `queue.sqlite`。监督器在启动工作负载前占有阶段锁，使用启动票据和配置身份匹配已持久化的运行记录。监督器与实际工作负载通过 Windows Job Object 约束为一棵可回收的进程树。管理器用 PID 与创建时间、阶段锁和启动票据重新识别运行。两阶段交接以 SQLite 记录的阶段索引为准。

## 验收命令

```powershell
python -m unittest discover -s tests -p test_inf1.py -v
logs/m1-pre1-cuda/Scripts/python.exe experiments/m1-dc1/test_dc1.py
python -m tools.training_manager resources
logs/m1-pre1-cuda/Scripts/python.exe -m tools.training_manager.audit_smoke --home smoke-acceptance
```

真实验收使用独立的 `smoke-acceptance` 队列，模板为示例的 102 轮与独立输出目录版本。在新队列中冻结、提交并选择 Full 后，可运行 `python -m tools.training_manager.verify_smoke --home <队列目录>`。脚本启动独立 PowerShell，再等该启动终端退出。它在经验阶段暂停并重启管理器，在 GPU 阶段暂停并恢复，完成后关闭管理器。

## 实测结果

| 验收 | 结果 |
| --- | --- |
| 轻量模拟 | 8 项通过，覆盖队列顺序、依赖、有限重试、身份冲突、预算、暂停恢复、模式切换、重复实例及进程故障。 |
| DC1 回归 | 4 项通过。 |
| 真实经验 | 第 16 根提交后暂停。管理器关闭并重启，完成 64 次尝试、64 条唯一结果、46 胜 18 败。两份战斗 SQLite 的完整性检查及压缩记录校验全部通过。 |
| 特征构建 | 56 条训练轨迹对应 664 行，8 条验证轨迹对应 91 行。分片哈希与索引一致。 |
| 真实 CUDA | RTX 4050 Laptop GPU，PyTorch 2.12.0+cu126。第 2 个 epoch、4 次更新后安全暂停，恢复至 3 个 epoch、6 次更新。60 份 AdamW 参数状态的步数均增加 6，最佳模型与配套 AdamW 检查点的权重及身份一致。 |
| 开发评测及摘要 | 8 次尝试、8 条唯一且完整的开发集记录。四阶段各完成一次，自动生成 JSON。 |
| 独立运行 | 启动用的两次 PowerShell 都已退出，后台管理器仍能运行。模拟另测了活动工作进程跨管理器异常退出继续运行，以及任务监督器崩溃后回收进程树。 |

本次运行用于检查基础设施。逐项哈希、计数和本地证据位置见[验收证据索引](../configs/training_jobs/inf1-evidence.json)。

## 验收边界

Windows 输入空闲转换、资源不足以及模式切换的调度行为通过注入测试。真实 Windows 资源检查读到交流供电、输入空闲时间、内存、磁盘和 RTX 4050。任务计划程序的脚本经过语法检查，注册需要项目负责人运行脚本。机器重启的恢复语义通过管理器进程故障和监督器进程故障模拟，实际重启 Windows 未纳入验收。CUDA 实跑使用 SV4A 延续训练，SV3A 独立训练适配器和完整正式 SV4A campaign 未另行实跑。

没有改动研究工作流的默认配置或历史实验资产。DC2A 的接口和提交方法见[操作手册](inf1-training-manager.md)。
