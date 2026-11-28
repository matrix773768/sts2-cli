"""Public conditional diagnostics: action selection uses only the current visible menu."""
def choose(name,depth,fallback,facts,prompt=None):
    if prompt:return fallback()
    actions=facts["actions"]
    end=next(a["index"] for a in actions if a["kind"]=="EndTurn")
    def find(card,target=None):
        for a in actions:
            if a["kind"]!="PlayCard" or facts["hand"][a["card"]]["id"]!=card:continue
            if target is None or (a["target"] is not None and facts["enemies"][a["target"]]["species"]==target):return a["index"]
        return end
    if name=="A-human":
        if depth<2:return find(("PRIMAL_FORCE","EXPECT_A_FIGHT")[depth])
        if depth<4:
            rocks=[a for a in actions if a["kind"]=="PlayCard" and facts["hand"][a["card"]]["id"]=="GIANT_ROCK"]
            if rocks:return (rocks[0] if depth==2 else rocks[-1])["index"]
        return end
    if name.startswith("B2-"):
        if depth==0:return find("IMPERVIOUS")
        if depth==1:return find("BODY_SLAM","BOWLBUG_EGG" if name=="B2-center" else "BOWLBUG_NECTAR")
        return find("STRIKE_IRONCLAD","BOWLBUG_ROCK") if depth==2 else end
    if depth==0:return find("SHRUG_IT_OFF")
    if name=="B1-blind":
        if depth==1:return find("DEFEND_IRONCLAD")
        return find("SETUP_STRIKE","BOWLBUG_EGG") if depth==2 else end
    if name=="B1-adapt":
        j=find("FLAME_BARRIER")
        return fallback() if j==end else j
    if name=="B3-adapt":
        threat=sum(sum(e["attack_hits"]) for e in facts["enemies"] if e["species"]=="BOWLBUG_ROCK")
        need=threat-facts["block"]
        if need>0:
            for a in actions:
                if a["kind"]=="PlayCard" and (a.get("block") or facts["hand"][a["card"]].get("block") or 0)>=need:return a["index"]
        return fallback()
    raise ValueError(name)
HUMAN={"A":["A-human"],"B1":["B1-adapt","B1-blind"],"B2":["B2-right","B2-center"],"B3":["B3-adapt"]}
