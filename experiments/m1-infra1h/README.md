# M1-INFRA-1H 运行入口

仓库起点为 `800310c631286a8cfb707e3d2a157d0d1017a66d`。以下 PowerShell 命令从仓库根目录运行。离线核验只使用 Git 中的证据和 Python 标准库。

```powershell
python -B experiments/m1-infra1h/export.py --verify
python -B experiments/m1-infra1h/summarize.py
```

## 本地资产与构建

运行战斗使用与 INFRA-0B 相同的 Windows、Python/PyTorch、.NET 9、STS2 v0.113.1 游戏文件、冻结模型与私有运行资产。0B 的 `infra_assets.py` 检查面板及原始宿主。1A 的 `build.py` 生成两个 `logs/infra1a-{5d,5e}-batch` 源码和产物目录。研究宿主使用这两个目录、0B 离线包源及原始 `lib/sts2.dll`。

上游归档位于同级目录 `../hk0-isolated-131d10a/upstream.zip`。同级 `../sts2-cli/logs/hotdraw-structures-build-03/build.json` 标识原 HotDraw 程序集、游戏目录和运行时，`../sts2-cli/logs/nuget-packages` 提供上游的离线包。该归档的 SHA-256、游戏 DLL 和两套宿主的哈希在构建时检查。产物身份保存在 `evidence/hosts.json`。原生游戏及模型二进制使用现有本地安装。

在具备这些输入的新运行目录，依次构建公共抽牌观察器、修正遥测的旧宿主、最终研究宿主。此前版本的构建标识 `engine`、`kernel2`、`kernel3`、`kernel4` 对应账本中的开发尝试。

```powershell
python -B experiments/m1-infra1h/campaign.py build-hot-k2 python -B experiments/m1-infra1h/hotbuild.py k2
python -B experiments/m1-infra1h/campaign.py build base2
python -B experiments/m1-infra1h/campaign.py build kernel5
python -B experiments/m1-infra1h/campaign.py build kernel6
```

## 生产与归因

`original`、`h-scalar`、`h-batch`、`h-kernel5` 分别选择冻结原版、生命周期遥测的标量旧版、相同遥测的 1A 批处理与最终混合宿主。一次运行启动一个 worker。处理次序、压缩及落盘边界来自 0B。每个运行名只能使用一次，所有计算命令通过 `campaign.py` 的同一把 Windows 文件锁串行记账，统一预算为 7,200 秒。复现实验可选新的 phase 名。完整重复整个实验需使用独立的运行目录和账本。

```powershell
python -B experiments/m1-infra1h/campaign.py run quick h-kernel5 natural --smoke
foreach ($panelName in 'natural','pairs','initial-train','initial-dev','audit') {
    python -B experiments/m1-infra1h/campaign.py run replica h-kernel5 $panelName
    if ($LASTEXITCODE -ne 0) { break }
}
python -B experiments/m1-infra1h/export.py
```

`--sample=12` 在冻结编号顺序上等距选取 12 个根，保留两个端点，作为明确标识的有界生产遍。`--profile` 开启 0B 的 Python/RPC 归因。研究宿主默认只在进程退出时汇总执行次数。下列环境变量单独控制诊断，使用值 `1` 启用。测正式吞吐时清除这些变量。

| 开关 | 含义 |
| --- | --- |
| `INFRA1H_REQUEST_RSS` | 恢复逐命令的 Windows 峰值采样和外层返回字段 |
| `INFRA1H_TIMERS` | 记录宿主内 Reference、分叉、绑定、规则与前沿耗时 |
| `INFRA1H_MODEL_CHECK` | 在相同真实前沿比较冻结 G2 单样本和批量的分数、概率、排序及 argmax |
| `INFRA1H_AUDIT_WORLD` | 在独立私有 Hot 状态上复放实际绑定，保存首个差异及 pre-draw C 的分项比较 |
| `INFRA1H_RELABEL` | 在真实抽牌窗口颠倒实例 ID 分配并重复从同一父节点分支 |
| `INFRA1H_FAIR` | 在 5E 可交换根上运行三次独立隐藏重排及完整 Planner 比较 |

`h-kernel4-g2` 和 `h-kernel6-g2` 是独立的数值实验。G2 以批量首选和次选的差距决定是否回到原单样本推理，分数绝对容差预设为 0.001。V2 与真实策略继续使用冻结的开局定义、价值组合和干预门槛。`h-kernel6-g2` 同时修正攻击资格检查：CORE 的公开 ally 数组包含玩家自身，单玩家场景要求唯一成员与玩家 HP 对应。

机制回归入口为 `regression.py hot` 和 `regression.py kernel5`。原生核验入口 `native_check.py infra1h-B-natural-h-kernel3` 使用已逐行对齐的自然面板，独立重放首个根、固定 154 和最长轨迹。`strategic_check.py infra1h-B-natural-h-kernel3` 在新宿主重放 96 根，导出 Hot C 字段、原编码/组合编码 SHA-256 与冻结 V2 效用。以上程序均可作为 `campaign.py <新标签> python -B ...` 的子命令记账。

`production.zip` 含逐行原始经验 gzip、运行参数、验收摘要、阶段计数、生命周期资源、诊断数据和构建/失败输出。比较时仅移除经验行最外层的 `seconds`。依据 `i` 核对每条记录，并从 0B 生产归档独立校验全量顺序与字段。原始压缩文件的 SHA-256 仍按整文件核对。
