# II-K.3A — 四条预测不支持见证

从 `port/v0.113.1@f1d3d77` 诊断，使用现有 `0.51.5-iik.2.4` 和 II-H.7 宿主。对 `logs/iij5b-serial-{pair16,holdout}/training.sqlite` 按套件、训练步和根 ID 只读提取规格、归档动作及策略，并对照各自的 `audit/<step>-<root>.json`。四根原策略快照均为 `cb2130276dd73a62703a8a0b955b92809fdd7db3b23f8e10719f73d40a4006a9`。原审计均为 `prediction_unsupported`，`prediction_stop_detail` 为空。

每根只复放一次归档路线。复用 II-G Completion 的双进程 `probe_prefix.py`，在动作后提取现有 `interaction_trace`，原生和 Solver 各自执行。四条均在最后一个归档动作阻断，之前的稳定原生续体戳全部一致。Solver 均为 `unsupported / solver_risk`，本步各自有 `<卡牌>.OnPlay: MethodNotMirrored`，原生均完成动作并留在 `combat_play`。没有重采、编译或 Solver 改动。本地摘要和复现脚本为 `logs/iik3a-probe.log` 与 `logs/iik3a-probe.py`，逐根结果在 `logs/iik3a-diagnosis/`，原生调用摘录在 `logs/iik3a-native.il`。

| 套件／根 | 场景 | 根种子／行为种子 | 首阻断索引与动作 |
| --- | --- | --- | --- |
| pair16 `0:000014` | Silent，Scrolls of Biting | `BF91C5AED2EE6839`／`1211241932748368222` | 18（19 个决策），回合 7，Sneaky |
| holdout `0:000014` | Defect，Chompers | `456B30D89E29C373`／`1211241932748368222` | 2（3 个决策），回合 2，One for All+ |
| holdout `0:000027` | Ironclad，Punch Construct | `D77A838176B97DE8`／`18016100648570524872` | 5（6 个决策），回合 3，Tank |
| holdout `1:000013` | Silent，The Obscura | `EF051BC6588675A4`／`14512733990261715723` | 19（20 个决策），回合 4，Blade Symphony |

以下 Solver 路径相对于现有候选的 `source/src/`。

- **Sneaky，已实现机制的覆盖缺口，低难度。** 原生 `Sneaky.OnPlay` 为自己施加 1 层 Sneaky Power，Solver 的 `P` 字段只缺这一项。出牌效果未在 `Prediction/CardEffectSpecRegistry.cs:35` 或 `Engine/InCombat/Mirrors/Cards/OnPlay/CardOnPlayMirrors.cs:71` 登记。下游已有 `Engine/InCombat/Mirrors/Hooks/Card/AfterCardPlayedMirrors.cs:835` 的他人攻击处理，联机语义仍需单独对照。最小夹具先核对普通／升级施加和叠层，再用本人攻击作负例、另一玩家攻击作正例，检查原生的触发目标与格挡量。
- **One for All+，缺失出牌及伤害机制，中等难度。** 原生 `OneForAll.OnPlay` 枚举战斗玩家并按人施加 Power，单人见证增加 4 层。Solver 的 `P` 字段缺这一项。上述出牌登记缺失，`Engine/InCombat/Mirrors/Hooks/Damage/ModifyDamageMirrors.cs:82` 的加法注册表也缺 `OneForAllPower`。其原生 `ModifyDamageAdditive` 区分 X 费、自动打出和实际能量花费／费用。最小夹具对照 0 费与非 0 费攻击，再覆盖减费至零、X 费及自动打出，另核对多人施加、拥有者归属和升级层数。
- **Tank，缺失出牌及伤害机制，中等难度。** 原生 `Tank.OnPlay` 为自己施加 1 层 Tank Power，当前实例的 `DamageDecrease=0.5`、`DamageIncrease=1.5`。Solver 的 `P` 字段缺这一项。上述出牌登记缺失，`Engine/InCombat/Mirrors/Hooks/Damage/ModifyDamageMirrors.cs:93` 的乘法注册表也缺 `TankPower`。原生 `ModifyDamageMultiplicative` 检查有动力攻击，区分持有者和受保护盟友。最小夹具核对同一敌击分别命中持有者及盟友的倍率，并以无动力伤害为负例。奥斯蒂是否属于保护对象应由原生对照确认。
- **Blade Symphony，已有生成能力的卡牌覆盖缺口，低至中等难度。** 原生 `BladeSymphony.OnPlay` 调用 `Shiv.CreateInHand`，见证中当前玩家手牌尾部增加两张普通 Shiv。Solver 的 `H` 字段少这两张牌。缺失 `CardOnPlayMirrors.cs:71` 的分派，可核对 `Engine/InCombat/Mirrors/Cards/OnPlay/BespokeCardMirrors.cs:272` 的手牌 Shiv 生成入口。最小夹具核对普通／升级数量、拥有者和手牌顺序，加一个手牌接近上限的边界。多人夹具用于确认各接收者与生成顺序。

## 根因分组与后续

共享阻断类别是出牌效果未覆盖。三条 Power 见证缺施加，Blade Symphony 缺手牌生成。One for All 和 Tank 还分别缺加法与乘法伤害钩子。四个首差均发生在具体效果上。两条 Silent 路线同时记录 `capture_store:CardPlayPairPredictionState`，且风险列表含此前动作，前缀精确匹配和本步字段缺失将首阻断定位在各自的 `OnPlay`。诊断未验证给缺失效果补齐后是否还会暴露捕获问题。

建议 **II-K.3B** 合并三项 Power 出牌及各自所需钩子，再把 Blade Symphony 作为独立生成改动纳入同一个候选构建。先各自跑最小原生夹具，再逐根复放冻结前缀和做定向同根重采。若多人夹具成为独立依赖，可先完成单人证据明确的修复，将需要独立验证的多人范围留给后续任务。发现新的首差时单独记录，累计全量验收留到里程碑。
