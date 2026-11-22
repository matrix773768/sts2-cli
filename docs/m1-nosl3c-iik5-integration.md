# II-K.5 — 累计定向与全量集成验收

## 运行身份与部署

验收起点 `port/v0.113.1@c57d6e557b44a5ad5479122440fd5ddf12d963e1`。使用 STS2 v0.113.1 Build 26660232、CoreCLR 9.0.7 和现有 Solver `0.51.5-iik.3b`。旧战斗宿主和常规部署保留。独立常规 Headless 从仓库源码构建，墙钟 8.8 秒。

| 实际入口或同目录依赖 | SHA-256 |
| --- | --- |
| `logs/iik3b-solver/bin/CombatSolver.dll` | `b4db8cae5abada95a3a51caac31bbae9f356fb553949b3c7d4b14ea10d181c53` |
| `logs/iik4b-host-final/Headless/bin/Debug/net9.0/OfflineSearchHarness.dll` | `b3f8ce1d862bdb98000bfeb90d701239e50be17034739c5c2ed18e26716150f0` |
| 同目录 `GodotSharp.dll` | `82b8ecbc4fee2f6490a27aa1a509c48b646bf9f35e5bfad07699487a539ca9aa` |
| `logs/iik5-main-host/bin/Debug/net9.0/Sts2Headless.dll` | `44ae4ef8309691310038a0a3f5199386e34c984198dfeda4e0f5f997161b0259` |
| 同目录 `GodotSharp.dll` | `66cea26b3cfb7d5c4047f0b3b10e49f5ec111753cdf88475305c9ee63266e5ff` |

验收绑定同时校验战斗宿主入口与 stub，运行账本的 `native_identity` 派生包含 stub 哈希。严格认证合同沿用 II-J.5B。Solver 和战斗宿主产物直接复用。

## 累计定向

全部采用最终 Solver／II-K.4B 宿主。Rattle 跨回合攻击计数、球体致胜锁定、Lightning Rod 两种减层边界、Glass Orb 同批终局衰减、Fossil Stalker 致死与非致死 Strength 夹具均精确。Sneaky、One for All、Tank、Blade Symphony 的九组单人夹具全部通过。Godot ABI、类型化信号、断开与一次性派发通过。Rolling Boulder 在三个 Inklet 上结算伤害后正常进入 Play。

沿用各阶段的单人边界。多人保护、发牌和触发尚无独立跑局认证。One for All 无出牌记录的费用回退、Rolling Boulder 图形渲染路径沿用既有覆盖边界。十一条见证的重采由固定套件提供，定向阶段只运行原夹具。

## 冻结历史与风险

65 条冻结历史全部复放。原 21 胜和 21 死严格认证及终局戳全部保留。18 条仅前缀、3 条无法重建、1 条历史执行失败及 1 条公开前缀差异均保留原分类。冻结执行器对未完成路线不提供同等逐边界独立原生戳，因此另运行八条原风险前缀；八条与 II-J.5B 的戳逐条一致（7／1／2／13／3／13／1／8 个稳定边界）。

八根固定策略重采全部严格认证（3 胜、5 死），沿用原根规格、行为种子和配置，终局戳与 II-J.5B 逐根一致。未重复运行风险直接探针或十一条定向同根重采。

## 固定套件

固定 pair16 已获 16/16 严格认证（15 胜、1 死），II-J.5B 的 12 条原认证与终局戳全部保留。运行读取固定课程、初始快照和整数种子，预算 128，优化关闭。下表以同一标准逐根对照定向证据。

| 套件与根 | 机制 | 决策／原生边界 | 严格结果 |
| --- | --- | ---: | --- |
| pair16 `0:000001` | Rolling Boulder | 37／37 | 胜 |
| pair16 `0:000006` | 球体致胜 | 16／16 | 胜 |
| pair16 `0:000009` | Rattle | 95／93 | 胜 |
| pair16 `0:000014` | Sneaky | 20／20 | 胜 |
| holdout `0:000014` | One for All | 22／22 | 胜 |
| holdout `0:000023` | Fossil Stalker | 10／10 | 败 |
| holdout `0:000027` | Tank | 15／15 | 败 |
| holdout `1:000010` | 球体致胜 | 16／16 | 胜 |
| holdout `1:000013` | Blade Symphony | 30／30 | 胜 |
| holdout `1:000020` | Lightning Rod | 18／18 | 胜 |
| holdout `1:000021` | Glass Orb | 21／21 | 胜 |

固定 holdout 为 59/60（37 胜、22 死）。原 52 条认证与终局戳全部保留。表中十一根与各自定向重采逐根比较，决策数、稳定原生边界数、认证分类、终局戳、公开观察、动作、行为 logp 全部一致。固定套件相对于 II-J.5B 的首个轨迹变化、旧新审计及行为种子见结构化证据。唯一剩余根 Axebot `1:000029` 仍为 128 预算的 `truncated / action_cap`，未产生认证终局，未扩展预算。

## v4 冷跑与恢复

两路首批 16 根从本轮 pair16 直接导入。冷跑一次进程完成两次更新，恢复路线提交首轮后重启完成第二次更新。32 条根记录的公开轨迹、行为 logp、认证与训练资格一致。三个事务快照逐字节一致，覆盖模型、Adam 与 Torch RNG。两步各使用 16、13 条严格轨迹，最大 logp 复算误差均为 `2.384185791015625e-07`。

最终模型 SHA-256 为 `bdc5c6e4dfa4ae45ea68a7eea0a746cca546c632fcb12dcfd41a60d59f9405a9`。本轮训练输入新增已认证轨迹，最终模型哈希随之变化。

## 完整主测试

首次运行 **164 通过、1 跳过、0 失败**。英文、中文和默认语言三项全部通过。唯一跳过仍为 `tests/test_save_load_cross_room.py:221` 的 S1 合法续体不足两条。保留原 JUnit 及标记警告。独立加载器探针确认新入口以 CoreCLR 9.0.7 启动，并将同目录 `GodotSharp.dll` 加入运行时程序集列表。追踪在 `logs/iik5-main-loader.log`。

| 阶段 | 墙钟秒数 |
| --- | ---: |
| 常规宿主构建 | 8.8 |
| 定向夹具（六条计时命令） | 107.9 |
| 冻结复放 | 159.0 |
| 风险前缀 | 44.5 |
| 八根风险重采 | 152.1 |
| pair16 | 78.9 |
| holdout | 210.7 |
| v4 初始化、导入、两路更新和比较 | 186.7 |
| 完整主测试 | 353.6 |
| **已计时阶段合计** | **1302.2** |

Rattle 在定向启动时单独执行一次，输出写入约 5.2 秒，ABI 与身份探针另计。各阶段串行，冻结、固定套件及 v4 沿用两名内部 worker。主测试的 pytest 内部计时为 351.07 秒。

## 基线建议

十一条修复见证全部获得与定向结果一致的严格认证。冻结 42 条、pair16 原 12 条、holdout 原 52 条及八根风险重采的认证和终局戳全部保留。固定套件唯一剩余项是 Axebot 的合理策略截断。新战斗和常规宿主在本轮验收范围内未发现回归。

**满足关闭 II-K 语义修复专项的条件。** 建议审查后将正式基线提升为 Solver `0.51.5-iik.3b`、II-K.4B 战斗宿主及本轮新部署的常规 Headless。正式基线目前仍为 `0.51.5-iij.4`。

## 复现

在仓库根使用新的运行前缀。若常规宿主尚未部署，先按下列路径构建一次。原 II-J.5B 账本及各阶段定向证据用于逐根比较；执行器只向新前缀写入输出。每阶段通过后再启动下一阶段。

```powershell
$env:DOTNET_CLI_HOME = (Resolve-Path logs/dotnet-home).Path
$env:NUGET_PACKAGES = (Resolve-Path logs/nuget-packages).Path
dotnet build src/Sts2Headless/Sts2Headless.csproj -o logs/iik5-main-host/bin/Debug/net9.0 -p:NuGetAudit=false
$h = 'experiments/m1-nosl3c-iik5'
$r = 'new-iik5'
foreach ($stage in @('fixtures','archive','prefix','samples','pair16','holdout','training','main')) {
    & "$h/run.ps1" -Stage $stage -Prefix $r
    python "$h/export_evidence.py" $r "logs/$r-$stage-gate.json"
    if ($LASTEXITCODE -ne 0) { throw "Acceptance gate failed: $stage" }
}
```

[结构化证据](../experiments/m1-nosl3c-iik5/evidence.json)
