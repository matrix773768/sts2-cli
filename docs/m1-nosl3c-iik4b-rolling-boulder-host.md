# II-K.4B — Rolling Boulder 宿主兼容性

起点 `port/v0.113.1@84c2925`。继续使用 Solver `0.51.5-iik.3b`（SHA-256 `b4db8cae5abada95a3a51caac31bbae9f356fb553949b3c7d4b14ea10d181c53`）、STS2 `0.113.1/26660232` 和 CoreCLR 9.0.7。正式全量验收基线为 `0.51.5-iij.4`。基线超时沿用 [II-K.4A 证据](m1-nosl3c-iik4a-residual-diagnosis.md)。

## ABI 与原生路径

`RollingBoulderPower.AfterPlayerTurnStart` 的图形分支在 VFX 对象上调用 `GodotObject.Connect(StringName, Callable, uint)` 注册 `HitCreature`。回调接收 `NCreature`，取出战斗实体并调度原生伤害，随后该分支等待 `Finished` 及伤害任务。它还引用了返回 `Variant` 的 `GodotObject.CallDeferred`，用于把 VFX 加入容器。两处签名都需由 JIT 解析。战斗宿主启用原生 TestMode，这一路径直接等待游戏原生 `DoDamage` 对当前可命中敌人结算。调用摘录保存在 `logs/iik4b-boulder.il`。

共享 GodotStubs 增加了基类 ABI、按名称连接和派发、断开及一次性连接。现有 `Callable` 支持把 Variant 中的对象交给类型化委托。基类 `CallDeferred` 支持无消息队列下所需的内联 `AddChild`。本轮验证支持常规和一次性连接，未模拟图形 VFX 或完整 Godot 场景循环。原生规则、Solver、认证合同及 5 秒回合等待均沿用原实现。

## 宿主产物与部署

II-K.4B 战斗宿主实际启动目录为 `logs/iik4b-host-final/Headless/bin/Debug/net9.0/`，运行入口及并列加载的共享 stub 如下。构建清单 `logs/iik4b-host-final/build.json` 保存绝对路径和摘要，复放与重采在绑定前校验两项。原 II-H.7 目录保留。

| 产物 | SHA-256 |
| --- | --- |
| `OfflineSearchHarness.dll`，原 II-H.7 入口 | `b3f8ce1d862bdb98000bfeb90d701239e50be17034739c5c2ed18e26716150f0` |
| `GodotSharp.dll`，II-K.4B stub | `82b8ecbc4fee2f6490a27aa1a509c48b646bf9f35e5bfad07699487a539ca9aa` |

成功编译一次，仅编译 GodotStubs，耗时 4.99 秒。此前两次启动分别止于 CLI 目录写权限及 NuGet 还原，未进入编译。最终使用工作区 CLI 目录和现有本地 NuGet 缓存。战斗宿主入口及 Solver DLL 直接复用。

最终累计验收用上表的独立战斗宿主配合 `iik.3b`。常规 Headless 引用同一份 GodotStubs 源码，应在累计验收时从 `src/Sts2Headless/Sts2Headless.csproj` 构建并部署整套输出到例如 `logs/iik4b-main-host/bin/Debug/net9.0`，让定位器可自该目录上溯五级到仓库根。常规测试的 `headless_runtime.ENGINE` 应指向新目录的 `Sts2Headless.dll`，并核对同目录 `GodotSharp.dll`。本轮只验证战斗宿主产物。

## 定向验收

| 检查 | 结果 | 耗时 |
| --- | --- | --- |
| ABI 与信号 | 反射验证精确签名和返回类型，发射信号确实将同一 Node 交给类型化委托，断开和一次性派发行为正确，验证基类 `CallDeferred(AddChild)` | 约 2 秒以内 |
| 最小 Rolling Boulder 夹具 | 打出后结束回合，三只 Inklet 从 14／13／16 降至 13／12／15 HP，原生进入下一回合 `Play` 的 `combat_play` | 2.23 秒 |
| 原冻结路线 | 37 个决策、37 个稳定原生边界均精确。索引 34 正常推进到第 13 回合，末步进入 `card_reward` | 5.14 秒 |
| 唯一一次同根重采 | 原模型、账本整数种子 `10494285998192343072`、128 动作预算、关闭优化。37 个决策和 37 个原生边界，完整历史前缀一致，`admissible_predicted_win / exact_native_match` | 根内 8.78 秒，脚本 11.69 秒 |

冻结复放与重采的终局戳均为 `e2eb734491d068dbbadf4485dc8a9ea710541179b4197efa8a8ceb6b62b17567`。Axebot `holdout 1:000029` 保留 128 预算的 `truncated / action_cap`。本轮未重采该根。

## 复现

从仓库根执行，使用新的输出目录。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$h = 'experiments/m1-nosl3c-iik4b'
$r = 'logs/new-iik4b'
$s = 'logs/iik3b-solver'
python "$h/build_host.py" "$r-host"
& "$h/verify_signals.ps1" "$r-host/Headless/bin/Debug/net9.0/GodotSharp.dll"
python "$h/verify_host.py" fixture "$r-fixture" $s "$r-host"
python "$h/verify_host.py" replay "$r-replay" $s "$r-host"
python "$h/verify_host.py" resample "$r-resample" $s "$r-host"
```
