"""Single deviations on a public legal menu. No backend state or card catalogue is required."""
from dataclasses import dataclass

@dataclass
class Deviation:
    menu: dict
    index: int
    kind: str
    incumbent: int

def select(visits, general):
    targets, other = [], []
    for menu, ranking in visits:
        actions = menu["actions"]
        incumbent = ranking[0]
        chosen = actions[incumbent]
        # Expand alternate target bindings of the exact same current hand instance.
        alternatives = [i for i in ranking[1:] if chosen["target_side"] == "enemy"
                        and actions[i]["target_side"] == "enemy" and actions[i]["kind"] == chosen["kind"]
                        and actions[i]["card"] == chosen["card"] and actions[i]["target"] != chosen["target"]]
        for i in alternatives:
            target = actions[i]["target"]
            foe = menu["enemies"][target]
            hits = actions[i].get("preview") or {}
            lethal = hits.get("damage_per_hit",0)*hits.get("hits",0) >= foe["hp"]+foe["block"]
            targets.append((not lethal, Deviation(menu,i,"target",incumbent)))
        if general:
            j = next((i for i in ranking[1:] if i not in alternatives and actions[i]["kind"]!="end_turn"),None)
            if j is not None:
                a = actions[j]
                preview = a.get("preview") or {}
                priority = (menu["decision"]["phase"]!="choice" and not preview.get("draw") and
                            not a.get("energy_x") and a.get("cost")==chosen.get("cost"))
                other.append((priority,Deviation(menu,j,"continue",incumbent)))
    def unique(items,cap):
        picked=[]
        for _,p in sorted(items,key=lambda t:t[0]):
            if any(p.menu==q.menu and p.index==q.index for q in picked):continue
            picked.append(p)
            if len(picked)==cap:break
        return picked
    return unique(targets,4)+unique(other,2)
