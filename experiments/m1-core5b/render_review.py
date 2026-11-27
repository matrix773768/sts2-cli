"""Render human-facing turn comparisons from the recorded simulator branches and local game text."""
from deploy5b import E,ROOT,FIVE,load_net,Evaluator
import gzip,json
from collections import defaultdict
from paths5b import RUN

def read(name):
    return json.loads((ROOT/"localization_zhs"/(name+".json")).read_text(encoding="utf-8-sig"))

cards,powers,monsters,encounters=map(read,("cards","powers","monsters","encounters"))
modifiers=read("enchantments")|read("afflictions")
def name(c):
    return cards.get(c+".title",c)
def card(c,show_cost=False):
    t=name(c["id"])+("+"*int(c.get("upgrade") or 0))
    if show_cost:t+="（"+str(c.get("cost"))+"费）"
    for field in ("affliction","enchantment"):
        if c.get(field):t+=f'〔{modifiers.get(c[field]+".title",c[field])} {c.get(field+"_amount") or ""}〕'
    return t
def stacks(p):
    return "、".join(powers.get(v["id"]+".title",v["id"])+str(v["amount"]) for v in p) or "无"
def actions(steps):
    out=[]
    for a in steps:
        k=a["kind"]
        if k=="play_card":
            s=name(a["card"])+("+"*int(a["upgrade"] or 0))
            if a["target"] is not None:s+=f'→敌{a["target"]+1}'
        elif k=="end_turn":s="结束"
        elif k=="select_candidate":s=f'选第{a["choice"]+1}项'
        elif k=="confirm_selection":s="确认选牌"
        else:s=k
        out.append(s)
    return "，".join(out) or "无已编译动作"

def enemy(e):
    dmg="＋".join(map(str,e["attack_hits"])) or "无直接攻击"
    return f'{e["hp"]}血/{e["block"]}甲，{dmg}，效果{stacks(e["powers"])}'
def outcome(r):
    return "死亡" if r["status"]=="death" else f'胜，剩 {r["terminal"]["hp"]} HP'
def showcase(d,ev):
    spec=d["spec"];t=d["turn"];s=d["right"]["snapshot"];h=s["h"]
    lines=[f'世界 `{spec["seed"]}`，{encounters.get(spec["encounter"]+".title",spec["encounter"])}。开局 {spec["hp"]}/{spec["max_hp"]} HP。第 {t} 回合决策时有 {h["hp"]} HP、{h["block"]} 格挡和 {h["energy"]} 能量。',"",
        "手牌按画面顺序为"+"、".join(card(v,True) for v in h["hand"])+"。","",
        f'抽牌堆余 {h["draw_count"]} 张。弃牌堆有'+("、".join(map(card,h["discard"])) or "零张牌")+"。消耗堆有"+("、".join(map(card,h["exhaust"])) or "零张牌")+"。战术菜单基础状态栏列出的玩家效果为"+stacks(h["powers"])+"。",""]
    pre=next((x for x in d["right"]["row"]["states"] if x["turn"]==t),None)
    if pre:
        lines.append("本回合抽牌前的完整 C 上，玩家持续效果为"+stacks(pre["powers"])+"。"+" ".join(
            f'敌{e["slot"]+1} 的持续效果为{stacks(e["powers"])}。' for e in pre["enemies"]))
        lines.append("")
    elif h["mechanism"]["stacks"]:
        for x in h["mechanism"]["stacks"]:
            owner="玩家" if x["owner"]==-1 else f'敌{x["owner"]+1}'
            lines.append(owner+"另有"+stacks([x])+"。")
        lines.append("")
    if d["tag"]=="loss":
        pick=json.loads((E/"pending-review.json").read_bytes())["rows"][0]
        chosen=card(pick["observation"]["decision"]["candidates"][pick["action"]["choice"]])
        lines.extend([f'头槌的实际待选是从弃牌堆置顶。表中的「选第4项」对应{chosen}，接着用战斗专注抽牌。[完整选牌菜单](../experiments/m1-core5b/evidence/pending-review.json)',""])
    for i,e in enumerate(h["enemies"]):
        species=h["mechanism"]["species"][i];intents={"Attack":"攻击","Defend":"防御","Debuff":"施加负面","Buff":"强化","DeathBlow":"致死","Unknown":"未知","Strategic":"特殊行动"}
        it="、".join(intents.get(x,x) for x in e["intents"])
        lines.append(f'- 敌{i+1} {monsters.get(species+".name",species)}，{enemy(e)}。当前意图为{it}。')
    lines+=["","| 执行或单回合替换 | 实际出牌顺序 | 同种子执行后进入的 C | V2 对该实际 C 的估值 | 整战结果 |","|---|---|---|---:|---|"]
    arms=[("左侧 "+d["a"],d["left"]),("右侧 "+d["b"],d["right"])]
    labels={"reference":"强制 G2 一回合","rival":"强制次选一回合","left_turn":"只切回左侧预算一回合"}
    arms.extend((labels[k],v) for k,v in d["alternates"].items())
    for label,b in arms:
        r=b["row"];c=next((x for x in r["states"] if x["turn"]==t+1),None)
        if c:
            cs=f'玩家 {c["hp"]}血/{c["block"]}甲；'+ " / ".join(f'敌{e["slot"]+1} {enemy(e)}' for e in c["enemies"])
            v=f'{ev({0:c},spec)[0]:+.2f}'
        else:cs="此回合终局" if r["terminal"] and r["terminal"]["turn"]==t else "未捕获";v="—"
        lines.append(f'| {label} | {actions(b["turns"][str(t)])} | {cs} | {v} | {outcome(r)} |')
    lines+=["","| 决策接口 | 完整参考质量 | G2 估值 | 最佳候选质量 | 最佳候选估值 | 实际决定 |","|---|---:|---:|---:|---:|---|"]
    for side in ("left","right"):
        q=next(q for q in d[side]["row"]["queries"] if q["turn"]==t)
        lines.append(f'| {d["a"] if side=="left" else d["b"]} | {q["reference_coverage"]:.2%} | {q["reference"]:+.2f} | {q["coverage"]:.2%} | {q["value"]:+.2f} | '+("干预" if q["used"] else "执行 G2")+" |")
    lines+=["","右侧搜索器的主要备选如下。每行给出一个不同首动作，以及该完整回合方案中概率最高的一条公开分支。方案均值对所有公开分支加权。",""]
    for p in s["plans"][:3]:
        z=max(p["leaves"],key=lambda x:x["p"]);v=z.get("value")
        leaf=(f'，该分支估值 {v:+.2f}' if v is not None and z["kind"] in ("C","victory","death") else "")
        lines.append(f'- {actions(z["actions"])}。方案均值 {p["value"]:+.2f}，已解决质量 {p["cov"]:.1%}。所示分支占 {z["p"]:.1%}，止于 {z["kind"]}{leaf}。')
    if d["oracle"]:
        w=d["oracle"];turns=defaultdict(list)
        for a in w["actions"]:
            txt=name(a["card_id"])+"+"*a["card_upgrade_level"] if a["kind"]=="PlayCard" else "结束"
            if a.get("target_combat_id") is not None:txt+=f'（战斗对象 {a["target_combat_id"]}）'
            turns[a["turn"]].append(txt)
        lines+=["",f'原生验证的 Oracle 胜路有 {w["length"]} 个动作，结束时 {w["end_hp"]} HP。对象号沿用原生见证。',""]+[f'- 第 {k} 回合：'+"，".join(v)+"。" for k,v in turns.items()]
    lines+=["",f'[逐动作轨迹、公开分支、完整 C 与反事实终局](../experiments/m1-core5b/evidence/review-{d["tag"]}.gz)']
    return lines

def main():
    ev=Evaluator(load_net(FIVE/"evidence/v2.pt","high"))
    intro="""# M1-CORE-5B 战斗复盘

本页选了五个世界。四个使用原始血量，一个使用 999 HP。每项比较使用同一副牌、同一遭遇和同一实现种子。这里的「胜」「死亡」来自整战模拟。标作原生验证的路线另在游戏宿主中执行到了战斗奖励。

C 是敌方行动结算完成、下一次正常抽牌之前的战略状态。表中的「实际 C」来自沿所列路线在这个种子上真实推进模拟器。模型给这个 C 的分数和决策前跨所有随机分支的均值可以不同。分数越高越好。未解决质量用 −50 占位，覆盖为零时读不出模型对该回合的意见。比较双方都使用严格完整质量和 +1 效用门槛。

「强制」行只替换当前回合，其他回合沿用右侧完整策略。第五回合专项使用基础策略作为共同前缀与续策。目标按敌方画面顺序从 1 起编号。手牌显示当前费用，+ 表示升级。完整的敌方条件、弃消耗牌状态、概率、待选菜单及后续动作保存在各案压缩 JSON 中。"""
    cases=[
    ("rescue","一、电球头的三连击，保住最后 1 HP","三个预算的图都已经生成「痛击+、耸肩无视、结束」的全部 11 个公开分支。基础预算只准其中 6 个进入结算，覆盖 61.5%；中档准入 9 个，覆盖 84.6%；高档准入全部 11 个，第一次有资格整体比较。实际下一轮敌人血量相同，玩家多出 6 HP。只替换这一回合就改变胜负，次选方案在同一续策下死亡。[逐节点结算审计](../experiments/m1-core5b/evidence/candidate-audit.json)"),
    ("loss","二、双敌暂时不攻击，模型高估了防守","高低预算都生成了同一个最高分候选。高预算使参考质量从 80% 变为完整，从而允许干预。火焰屏障保留格挡，却少造成 21 点伤害。只强制执行一次 G2，随后继续高预算即剩 29 HP 获胜。这个隐藏实现上，模型高估了防守相对集中输出的收益；一次反事实无法判定整条公开概率分布上的期望次序。"),
    ("recovery","三、方块构装体，放通已经生成的攻击方案","原系统已经生成同一高分方案。首回合的参考推进中断，导致它没有执行资格。修复后，攻击方案让敌人少 8 HP 带入下一回合。此时敌人有力量 2、人工制品 1，准备造成 9 点攻击。后续同用修复策略时，本回合出攻击比跟 G2 多留 23 HP。原系统整战死亡还包含以后各回合的差异。"),
    ("oracle","四、三骑士，原生有胜路，公开搜索缺少合格候选","双方实际采用相同的 G2 路线。高预算已把参考质量提至 99% 以上，候选质量仍为零，候选侧遇到敌方条件转换。Oracle 枚举的完整未来中，改变首回合顺序并配合后四回合可获胜。该见证证明整个根可解，单独调整首回合能否取胜仍待验证。"),
    ("long","五、999 HP 的沙坑 Boss，先区分第一次分歧与决定性回合","两条完整策略第一次在第三回合分歧，遭受的直接伤害相同。将基础策略的第三回合移入高预算续策仍以 840 HP 获胜。直接用 G2 替换该回合则以 880 HP 获胜。因此不能把两条完整路线相差的 840 HP 归到这次出牌顺序上。"),
    ("fifth","同一场 Boss 战的第五回合","沿基础策略的同一前缀，依次只给八个回合中的一个增加预算。仅替换第五回合，随后恢复基础预算，即以 840 HP 获胜。替换另七个回合仍死亡。基础预算已经给「突破、狂乱逃离、结束」打出 +14.73 分。决定性差异在参考分支：基础预算只完成 6.67%，高预算完成 100%。打短线后，玩家眼前还少 1 HP、敌人多 15 HP，但保留的牌和后续轮转足以兑现胜利。")]
    lines=[intro]
    for tag,title,comment in cases:
        d=json.load(gzip.open(E/f"review-{tag}.gz"));lines+=["","## "+title,"",comment,""]+showcase(d,ev)
    lines+=["","[八次单回合替换的逐次结果](../experiments/m1-core5b/evidence/long-turns.json)",""]
    ((RUN if RUN else ROOT/"docs")/"m1-core5b-battle-review.md").write_text("\n".join(lines),encoding="utf8")
if __name__=="__main__":main()
