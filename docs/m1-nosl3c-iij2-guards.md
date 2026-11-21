# II-J.2 Guards Transform 选择数量合同

候选 Solver `0.51.5-iij.2` 继承 II-J.1，使用 II-H.7 战斗宿主、CoreCLR 9.0.7、STS2 v0.113.1 Build 26660232。全量验收基线为 `0.51.5-iii.8`。

Solver 从固定版本 Guards 原生 OnPlay 的 CardSelectorPrefs 声明读取上下限，由共享选择规格发布。候选实例列表继续约束可执行动作。共享 v3 投影允许声明上限超过实际候选数，继续严格检查实例索引、选择数量和完整动作菜单。原生审计仍精确比较公开数量。

## 原生定向验证

普通 Guards 独立进程夹具以 `0:000020` 的固定初态分别空选、单选、全选。公开菜单、确认后的合法动作和包含牌区与 RNG 的原生稳定续体戳均精确匹配。越界 Solver 动作被拒绝，随后合法确认成功。只读归档复放在两条原菜单边界通过，夹具确认另计。

| 根 | 菜单索引 | 旧公布上限 | 新公布上限 | 同根重采 |
| --- | ---: | ---: | ---: | --- |
| `0:000020` | 2 | 3 | 999999999 | 10 决策，8 原生边界，严格败局 |
| `1:000005` | 4 | 6 | 999999999 | 32 决策，26 原生边界，严格败局 |

重采逐根读取原策略快照、行为种子和根规格，预算 128，各执行一次，优化关闭。共同前缀分别为 2、4 决策，首变均来自 Guards 菜单上限，首个选择动作仍分别选索引 2、3。新采集逐根保存在独立 JSON 记录中。

Quasar 普通、升级和空选通过，CLEANSE 同名同升级实例及完整胜局通过，Survivor 固定一张确认后的原生续体精确匹配。其后原档仍到达独立的 Hidden Daggers+ 错误。本轮只执行定向验证。首次夹具运行发现共享 Python 投影仍把声明上限限制在候选数内，修正后通过。

[构建与逐根证据](../experiments/m1-nosl3c-iij2/evidence.json)

## 复现

从仓库根运行，使用新的日志前缀。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$r = 'new-iij2'
$s = "logs/$r-solver"
$h = 'experiments/m1-nosl3c-iij2'
$j = 'experiments/m1-nosl3c-iij1'
python "$h/build_solver.py" $s
python "$h/verify_guards.py" "logs/$r-guards" $s
python "$h/resample.py" "logs/$r-resample" $s
python "$j/verify_choices.py" quasar "logs/$r-quasar" $s
python "$j/verify_choices.py" instances "logs/$r-instances" $s
python "$j/verify_choices.py" related "logs/$r-survivor" $s
python "$h/export_evidence.py" "logs/$r-evidence.json" --prefix $r --solver $s
```
