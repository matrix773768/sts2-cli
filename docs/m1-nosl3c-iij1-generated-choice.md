# II-J.1 交互选择实例与来源绑定

定向候选 `0.51.5-iij.1` 继承 `0.51.5-iii.8`，配对 II-H.7 战斗宿主、STS2 v0.113.1 Build 26660232 和 CoreCLR 9.0.7。正式全量验收基线仍为 `0.51.5-iii.8`。

## 修复与定向验证

Quasar 原生从无色卡池用 CombatCardGeneration RNG 生成三个不同候选，升级版先升级整组，再打开可空选的选择器。确认后只有选中的牌进入手牌。原 Solver 的候选能正常发布，但生成选项的 `SourcePile=None`，来源实例列表为空，因此共享确认代码无法按引用构建选择令牌。

生成类卡牌与药水现在共用选择规格，以当前捕获的选项批次作为来源实例列表。确认仍按实例引用定位，并用包含升级状态的语义键和组内出现次序编码。已有牌区的来源校验、公开菜单、选择数量、所有权及现有入堆流程保持原合同。

- 独立原生 Quasar 夹具比较候选顺序、升级、选择上下限、确认后的完整续体、手牌、抽牌堆、RNG 和合法动作。普通与升级版均选中 Panache 并精确匹配。Quasar 候选本身互异。
- 预测端拒绝超出菜单的候选索引，之后仍可合法确认。原生测试适配器会把无效索引过滤为空选。独立空选对照验证无候选入手且续体精确匹配。首次夹具误把原生适配器的过滤行为当作错误响应，另一次导出假定成功响应有 `detail` 字段。两次初始失败日志保留。
- Glimpse Beyond 普通、升级与 RNG 三组记录与 II-I.8 一致。CLEANSE 同名同升级的候选索引 1、3 分别绑定到两个实际实例，抽牌堆结果不同且均精确匹配原生。该夹具另有一条严格胜局。药水共用本次来源规格，未单独运行药水夹具。

## 同根重采

II-E `1:000003` 沿用 pair16 固定配置，预算 128，优化关闭，新账本单独保存。前四个决策与 II-I.9A 相同，第五个决策成功确认 Panache。新路线共 66 个决策，58 个稳定原生边界匹配，终局为 `admissible_death / exact_native_match`。

## 三个关联见证

| 见证 | 修复前后 | 机制判断 |
| --- | --- | --- |
| 独立 16 根 `0:000004` | Survivor 确认后仍精确匹配。两版均在索引 8 打出 Hidden Daggers+ 时报执行错误 | 手中仅剩一张可弃牌，Solver 固定数量规格仍要求弃两张，与隐式全选分支的候选数不符 |
| 独立 60 根 `0:000020` | 两版均在索引 2 打开 Guards 的 Transform 菜单时失配 | 原生声明上限 999999999，Solver 发布上限 3 |
| 独立 60 根 `1:000005` | 两版均在索引 4 打开 Guards 的 Transform 菜单时失配 | 原生声明上限 999999999，Solver 发布上限 6 |

两条 Guards 路线的候选身份和顺序一致，首个差异在选择数量合同。三个见证均使用已有手牌实例，独立于生成候选来源。证据保留原始审计及两版只读定向复放结果。

[构建与逐根证据](../experiments/m1-nosl3c-iij1/evidence.json)

## 最小复现

从仓库根使用新目录。关联复放只读 II-I.9B 的三个已采集根。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$h = 'experiments/m1-nosl3c-iij1'
$s = 'logs/new-iij1-solver'
$b = 'logs/m1-nosl3c-iii8-candidate'
python "$h/build_solver.py" $s
python "$h/verify_choices.py" quasar logs/new-iij1-quasar-proof $s
python "$h/verify_choices.py" related logs/new-iij1-related-base $b
python "$h/verify_choices.py" related logs/new-iij1-related $s
python "$h/verify_choices.py" instances logs/new-iij1-instances $s
python experiments/m1-nosl3c-iii7/verify_glimpse.py logs/new-iij1-glimpse --solver $s
python experiments/m1-nosl3c-iii8/verify_root.py resample logs/new-iij1-resample $s
python "$h/export_evidence.py" "$h/evidence.json"
```

末行导出本轮日志生成的证据。复跑时用 `--prefix new-iij1 --solver $s` 并指定新的证据输出路径。
