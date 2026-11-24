# INF1 Windows 训练管理器

INF1 在 Windows 登录会话内独立管理本机训练队列。默认队列、日志和报告都在 `logs/inf1/`。日常操作从仓库根目录执行。计算期间 Windows 必须处于唤醒状态，睡眠、休眠或关机都会停止计算。

## 日常操作

双击 `tools/training_manager/start-inf1.cmd` 启动后台管理器。PowerShell 中使用以下命令。

```powershell
$inf1 = '.\tools\training_manager\inf1.ps1'
& $inf1 start
& $inf1 status
& $inf1 mode Full
& $inf1 pause sts2-smoke
& $inf1 resume sts2-smoke
& $inf1 report sts2-smoke
& $inf1 shutdown
```

默认脚本使用 PATH 中的 `python.exe`。可以提前设置 `$env:INF1_PYTHON` 指定管理器解释器。任务使用其配置里冻结的解释器，CUDA 示例使用仓库已有的 `logs/m1-pre1-cuda/Scripts/python.exe`。Windows 沙箱如果禁止脱离其 Job Object，后台启动会报拒绝访问。在普通 PowerShell 中运行上述命令，或用 `start --foreground` 保持前台终端。

| 操作 | 命令与结果 |
| --- | --- |
| 查看队列 | `& $inf1 list` 显示状态、阶段、进度和等待原因。 |
| 查看详细进度 | `& $inf1 status <任务ID>` 显示本阶段计数、检查点、累计运行及暂停时间、每次启动的参数和日志。 |
| 查资源 | `& $inf1 resources` 读取 Windows 内存、磁盘、电源、输入空闲时间，以及 NVIDIA GPU 信息。JSON 中的 `null` 表示不可用。 |
| 暂停 | `& $inf1 pause <任务ID>` 后等待状态变为 `paused`。完成当前阶段也可能直接进入 `completed`。 |
| 恢复 | `& $inf1 resume <任务ID>` 重新进入队列。阶段边界和资源条件仍然适用。 |
| 安全取消 | `& $inf1 cancel <任务ID>` 在安全边界停止。 |
| 立即取消 | `& $inf1 cancel <任务ID> --force` 终止该次运行的 Windows 进程树。最后一个正在写入的工作单元可能丢失。 |
| 重试失败或中断 | `& $inf1 retry <任务ID>` 使用剩余已批准重试额度。可恢复阶段在仍有额度时也会自动重试。 |
| 停止所有计算 | `& $inf1 stop-all` 请求当前任务停到安全边界，并停止发送新任务。用 `& $inf1 enable` 重新允许调度。 |
| 彻底关闭 | `& $inf1 shutdown` 停止调度，请求活动任务安全退出，然后退出管理器。下次启动后用 `enable` 恢复调度。 |
| 查看结果 | `& $inf1 report <任务ID>` 输出 JSON。终态报告也自动写到 `logs/inf1/jobs/<任务ID>/report.json`。 |

用户暂停的任务在重新开机后继续保持暂停。重启管理器时会读取 SQLite，并识别仍由原监督器持有的运行。若 Windows 或任务监督器异常退出，重启后会把失去监督且没有退出记录的任务记为 `interrupted`。可恢复阶段按剩余重试额度从最近完整提交恢复。暂停时进程会退出并释放显存和锁。

## 运行模式和保护

| 模式 | 启动及暂停行为 |
| --- | --- |
| Full | 用批准的正常资源配置，仍执行内存、磁盘、电源及 GPU 检查。通过 `mode Full` 主动启用。 |
| Idle | 初始模式。默认插电且连续 600 秒无输入后才启动。重新操作电脑会请求重任务在边界暂停，再次闲置后自动恢复。 |
| Light | 运行轻量 CPU 阶段。重 CPU 阶段必须有明确的低负载参数，GPU 阶段等待。切换已有低负载参数的阶段时，在边界退出后按新参数重启。 |

可选的 `logs/inf1/settings.json` 示例如下。CLI 已设定的模式和启停开关会保存在队列数据库中。

```json
{
  "mode": "Idle",
  "idle_seconds": 600,
  "poll_seconds": 1,
  "min_disk_mb": 2048,
  "min_ram_mb": 1536,
  "min_vram_mb": 512,
  "resource_samples": 3,
  "require_ac": true
}
```

资源不足时暂缓发车。运行中连续采样不足时请求安全暂停，掉电和 Idle 下恢复输入会直接请求暂停。Idle 始终要求插电。GPU 检查使用 `nvidia-smi` 的第一个设备，CUDA 适配器会在任务解释器中实际检查 CUDA 可用性。各阶段可以提高所需资源。INF1 只在默认队列串行调度，验收用的 `--home` 独立队列也应按顺序运行。

## 提交已批准的计划

从 [示例计划](../configs/training_jobs/sts2-smoke.json) 开始，替换任务 ID、输出目录、环境、输入资产和阶段命令。模板中的 ID 必须对应一个全新输出目录。冻结会计算当前 Git 基线、Python 可执行文件、阶段脚本和所列输入文件的 SHA-256。提交前在冻结文件中核对预算、数据队列和实际参数。

```powershell
& $inf1 freeze configs/training_jobs/sts2-smoke.json logs/inf1/sts2-smoke.frozen.json
& $inf1 submit logs/inf1/sts2-smoke.frozen.json
& $inf1 start
& $inf1 mode Full
```

每个阶段用 Python 脚本和参数数组启动。第一个参数是仓库相对脚本路径。其余参数中的 `{repo}`、`{output}`、`{work}` 分别展开为仓库、任务目录和阶段目录。阶段按列表顺序运行，`depends_on` 指定在前的必要阶段。阶段失败时后续阶段保持未运行。

- `mode` 指定 `Full`、`Idle`、`Light` 或 `Any`。阶段声明 `gpu`、`heavy`、`workers`，可声明 `light_workers` 和 `light_args`。
- `max_retries` 是整个计划的重试额度。`budget_seconds` 累计各次受监督执行的耗时，包括工作进程初始化。到期后请求合作停止，超过 `stop_grace_seconds` 后清理进程树。阶段的固定根数、epoch、更新数及评测队列随参数冻结。
- 多代计划将每代有限阶段直接列出，使用 `limits` 记录最大代数、每代经验目标及尝试上限、更新预算、评测队列和停止规则。任何早停规则由被批准的适配器实现，CLI 按其正式退出和提交结果推进。
- 模板可引用历史产物作为只读输入。管理器防止重用输出目录并核对身份。阶段命令是受信任的本地代码，执行使用当前用户权限，输出和数据用途由审核过的参数及适配器约束。

## 暂停协议和 STS2 接入

合作式阶段读取 `INF1_STOP` 对应的停止文件，并通过原子写入 `INF1_PROGRESS` 报告 `done`、`target`、最近已提交检查点及吞吐。从安全边界退出时返回 75，达到已提交的目标时返回 0。进度中列出的检查点必须位于阶段目录，其内容由适配器验证。适配器恢复时要重新读取真实账本或检查点，进度 JSON 用于观察。

| 接入入口 | 最小停止边界 |
| --- | --- |
| `sts2.py dc1` | 已派发的根组提交后，退出常驻 PRE0B 宿主。示例 Full 最多 8 根，Light 最多 2 根。两份参数保持同一个账本身份。 |
| `sts2.py features` | 使用 SV3A 编码和分片机制，完成一个可验证的分片组后提交索引。示例最多 16 根。 |
| `sts2.py sv4-train` / `sv3-train` | 一个完整 epoch 的优化更新、验证和原子 `resume.pt` 保存。进程在模型、AdamW、调度器和随机状态保存后退出。训练脚本的准备和首轮验证也可能计入等待时间。 |
| `sts2.py development` | 已提交的开发根组。示例最多 2 根，入口检查开发用途及与经验根的隔离。 |
| 其他已批准入口 | `resume: restart` 表示入口明确支持从头重跑该阶段。`resume: none` 表示只能等当前阶段自然结束，失败后该阶段无法由 INF1 续跑。 |

战斗崩溃时已提交的 ordinal 保留，未提交根组重新分配。训练崩溃时最多丢失当前未提交 epoch 的更新及验证耗时。以原入口设置为例，完整 SV4A epoch 有 192 次更新，等待时间还取决于当前数据验证和 I/O。SV3A 与 SV4A 的训练器沿用原有模型及优化器恢复语义。

正式 SV4A campaign 仍可作为整体运行。用明确批准的 `--until pretest` 或单路 `--route D`、`--route S` 控制范围。若希望拥有上述停止粒度，应提交按阶段拆开的命令。源 campaign 的双路默认路径包含正式确认阶段，需要单独批准后才能提交相应命令。

## 可选登录自动启动

在普通 Windows PowerShell 中运行下列脚本。注册绑定当前 Windows 用户登录，使用任务计划程序的重复实例抑制，加上 INF1 队列锁。登录后可重新接管或识别未完成任务。

```powershell
.\tools\training_manager\autostart.ps1 -Action Register
.\tools\training_manager\autostart.ps1 -Action Status
.\tools\training_manager\autostart.ps1 -Action Unregister
```

如要完全关闭，先运行 `shutdown`，待状态中的进程消失后再卸载开机任务。

## DC2A 接入

另建 `configs/training_jobs/dc2a-*.json`，审批后冻结新的 DC2A 模型设计、战损分布、训练与开发样本清单、历史只读输入和有限算力预算。独立的 DC2A 阶段入口按上述协议发布账本或模型检查点，经验、特征、训练和开发评测显式连接。每次提交分配新的任务 ID 和输出目录。
