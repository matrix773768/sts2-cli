# II-J.3 Hidden Daggers 固定数量选择

定向候选 `0.51.5-iij.3` 继承 II-J.2，配对 II-H.7 战斗宿主、CoreCLR 9.0.7 和 STS2 v0.113.1 Build 26660232。正式全量验收基线为 `0.51.5-iii.8`。

Hidden Daggers 的原生 OnPlay 调用 FromHandForDiscard，再按返回顺序弃牌，最后调用 Shiv.CreateInHand。普通和升级版均要求弃两张并生成两张 Shiv。独立原生夹具先确认了以下行为，再实施修复。

| 剩余候选 | 原生交互 | 弃牌 |
| ---: | --- | --- |
| 0 | 直接结算 | 0 张 |
| 1 | 直接结算 | 唯一候选 |
| 2 | 直接结算 | 按手牌顺序弃全部 |
| 3 | 显式菜单，确认要求恰好选 2 张 | 夹具选择菜单前两张 |

共享续体确认对引擎已标记为隐式全选的请求按实际候选数量校验，保留唯一索引和实例绑定校验。显式确认继续使用声明上下限，包括 Guards 的公开上限。普通和升级版各四个用例的公开菜单、弃牌与生成、牌区、RNG、稳定续体及后续合法动作均与独立原生匹配。

## 历史复放与一次重采

独立 16 根 `0:000004` 的九个归档动作全部通过。Survivor 在索引 6 确认后、Hidden Daggers+ 在索引 8 出牌后分别取得精确稳定续体戳。一次同根重采使用原 pair16 策略快照、行为种子和 128 决策预算，关闭优化。前八个决策记录一致，索引 8 仍打出 Hidden Daggers+，现已完成弃牌和生成。新轨迹 37 决策、33 个原生边界，取得 `admissible_predicted_win / exact_native_match`，无新增原生首差。完整重采记录保存在独立 JSON。

Guards 空选、单选、全选及两条旧菜单边界通过。Quasar 普通版、升级版和空选、CLEANSE 实例绑定及 Survivor 固定数量确认均通过。本轮只执行定向验证。

[构建与逐根证据](../experiments/m1-nosl3c-iij3/evidence.json)

## 复现

从仓库根运行，使用新的日志前缀。

```powershell
$env:STS2_DOTNET = (Resolve-Path logs/m0-v5/dotnet9/dotnet.exe).Path
$env:STS2_DOTNET_VERSION = '9.0.7'
$env:PYTHONUTF8 = '1'
$r = 'new-iij3'
$s = "logs/$r-solver"
$h = 'experiments/m1-nosl3c-iij3'
$j = 'experiments/m1-nosl3c-iij1'
$g = 'experiments/m1-nosl3c-iij2'
python "$h/verify_daggers.py" native "logs/$r-native" logs/iij2-solver-final
python "$h/build_solver.py" $s
python "$h/verify_daggers.py" compare "logs/$r-fixtures" $s
python "$j/verify_choices.py" related "logs/$r-related" $s
python "$h/resample_pair.py" "logs/$r-resample" $s
python "$g/verify_guards.py" "logs/$r-guards" $s
python "$j/verify_choices.py" quasar "logs/$r-quasar" $s
python "$j/verify_choices.py" instances "logs/$r-cleanse" $s
python "$h/export_evidence.py" "logs/$r-evidence.json" --prefix $r
```
