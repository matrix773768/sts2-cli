# INF2 实施与验收

基线为 `port/v0.113.1` 的 `4e5a3e025f368279f045d4f4645054c79164016b`。

## 接入

- Python 标准库提供回环 HTTP 服务，原生 HTML、CSS 和 JavaScript 提供五个中文页面。后台 Windows 服务用 INF1 的脱离进程能力，队列由现有 INF1 类与 CLI 控制。
- 启动器根据回环健康地址和队列身份识别已有服务。HTTP 控制要求可信启动会话、精确 Host 和 Origin、同源请求及 CSRF。文件浏览逐级核对任务目录和允许的产物，拒绝路径重定向。
- 两个正式 DC2B 配置保留现有命令、阶段和预算，并把新增的账本身份读取源码纳入冻结哈希。课程门槛使用成功完成的初始任务和实际评测退出记录，核对原开发评测与已提交模型的账本身份。复杂构筑开发对照产物也必须存在且身份一致。
- DC2B 进度分别记录已提交更新、完整战斗目标和尝试数。达到完整战斗目标后的提早完成与 INF1 完成协议一致。报告记录课程排程中达到晋级条件的家族数。进度沿用 INF1 原子更新与 Windows 短暂文件共享冲突重试。正式学习目标、模型、阈值、根数和预算沿用原定义。
- 结果页使用历史 D2 的原开发资料作为 D2 基线。G0-DC 与课程代数读取各自的实际任务产物。验证 NLL、死亡 Brier 以每层验证样本数加权，胜局绝对净战损 MAE 按胜局样本数加权。训练损失取每个已提交更新点记录的最后一个训练批次。

## 可复验入口

```powershell
python -m unittest discover -s tests -p test_inf2.py -v
python -m unittest discover -s tests -p test_inf1.py -v
logs/m1-pre1-cuda/Scripts/python.exe experiments/m1-dc2b/test_dc2b.py
```

浏览器验收脚本 `tests/inf2_browser.mjs` 用已有 Microsoft Edge 和 Node.js 测试运行器。Node.js 仅用于自动化验收。脚本需要普通 Windows 登录会话、可用回环网络、CUDA 虚拟环境和项目已有输入资产。以全新队列名运行 `node tests/inf2_browser.mjs inf2-browser-verify` 可重新执行。它会生成实际界面截图、读取复制的 Markdown，并关闭由验收启动的服务。日常使用从 [中文操作手册](inf2-training-dashboard.md) 开始。

## 实机验收结果

| 项目 | 结果 |
| --- | --- |
| Windows 启动器与独立进程 | Windows 批处理入口成功调用默认浏览器。重复启动复用既有 Web 服务。通过 Edge 页面启动独立 INF1，验证在线、调度与任务状态分开。 |
| 模式与控制 | Edge 成功切换 Full、Idle、Light。活动任务安全暂停，全局停止也通过有实际工作进程的测试。 |
| 正式计划与隔离提交 | 实际配置页面显示两份 DC2B 计划。课程冻结请求因初始任务尚未提交被拒绝。通过界面审核、冻结和确认提交了隔离的 `inf2-smoke`。 |
| 安全暂停与恢复 | 在第 12 次 CUDA 更新处暂停，恢复后关闭测试浏览器，后台推进至第 16 次并最终完成 80 次更新。60 份 AdamW 参数状态的计数都为 80，部署权重与恢复检查点一致。 |
| 结果和剪贴板 | 重开 Edge 后读取 8 条完整开发评测记录。开发账本完整性、记录哈希及模型身份一致。真实训练曲线正常显示，Markdown 实际写入剪贴板并回读核对。 |
| 权限、路径、冲突与回归 | 7 项 INF2 测试、8 项 INF1 回归和 3 项 DC2B 回归通过。验证了跨源、缺失会话或 CSRF、重复任务、输出冲突、路径穿越及 Windows 目录重定向均被拒绝。 |
| 收尾 | 验收后关闭启动的后台管理器和 Web 服务。正式队列中没有两项 DC2B 任务记录。 |

真实验收使用 `logs/inf1/inf2-final-verified`，受监督耗时约 44 秒。[证据索引](../configs/training_jobs/inf2-evidence.json)包含冻结任务、SQLite、模型、验证指标、剪贴板回读和截图的 SHA-256。

实际截图 [训练计划](images/inf2-plans.png)、[安全暂停后的队列](images/inf2-queue.png)、[正式结果比较](images/inf2-results.png)、[真实 CUDA 训练曲线](images/inf2-training.png)。

桌面快捷方式脚本完成语法检查。手动验证可在资源管理器双击 `start-dashboard.cmd`，确认浏览器出现五个中文页面，再到训练总览检查 INF1 状态。完整 DC2B 初始任务和后续课程未运行，课程正向放行用已完成记录与模型绑定的模拟账本测试，实际队列验证的是初始任务缺失时的拒绝。
