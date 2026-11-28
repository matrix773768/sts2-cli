"""Portable legal-menu scorer. The learner sees only a public decision and public history."""
from functools import lru_cache
import numpy as np
from torch import nn
from common6 import public_summary, powers, token, variant, torch

EFFECTS = ("Damage","Block","Draw","GainEnergy","GainPower","ApplyPower","Exhaust","Discard","GenerateCard","Heal","LoseHp")
KINDS = ("play_card","end_turn","select_candidate","confirm_selection")

@lru_cache(maxsize=4096)
def effects(card, upgrade):
    kinds = {e.get("kind") for e in variant(card, upgrade)[1].get("effects", [])}
    return tuple(float(k in kinds) for k in EFFECTS)

def encode(obs, history, opening):
    hand, enemies = obs["hand"], obs["enemies"]
    candidates = obs["decision"].get("candidates", [])
    sketch = np.zeros(24, dtype=np.float32)
    for c in hand:
        sketch[token(c["id"]) % len(sketch)] += .25
    context = [*public_summary(obs), *powers(obs), opening["hp"]/100, obs["stars"]/5,
               len(obs["discard"])/20, len(obs["exhaust"])/20, len(enemies)/4,
               token(obs["decision"].get("pile"))/512, *sketch, *history[1]]
    rows, ids = [], []
    for a in obs["actions"]:
        assert a["index"] == len(rows)
        card = hand[a["card"]] if a["card"] is not None else candidates[a["choice"]] if a.get("choice") is not None else {}
        target = enemies[a["target"]] if a["target_side"]=="enemy" else {}
        p = a.get("preview") or {}
        cid = card.get("id","")
        up = card.get("upgrade",0)
        numeric = [*(float(a["kind"]==k) for k in KINDS), (card.get("index", -1)+1)/10, up/3,
                   (a["cost"] or 0)/5, float(a["cost"] is None),float(bool(a.get("energy_x"))),
                   p.get("damage_per_hit",0)/25,p.get("hits",0)/5,p.get("block",0)/20,p.get("draw",0)/4,
                   (target.get("index",-1)+1)/4, min(target.get("hp",0),1000)/100,
                   target.get("block",0)/20,sum(target.get("attack_hits",[]))/30,
                   *powers(target or {"powers":[]}), *effects(cid,up)]
        rows.append([*context,*numeric])
        ids.append(token(cid) if cid else 0)
    return np.asarray(rows,dtype=np.float32), np.asarray(ids,dtype=np.int64)

class MenuPolicy(nn.Module):
    def __init__(self,width):
        super().__init__()
        self.cards = nn.Embedding(512,16)
        self.action = nn.Sequential(nn.Linear(width+16,64),nn.SiLU(),nn.Linear(64,48),nn.SiLU())
        self.score = nn.Sequential(nn.Linear(96,48),nn.SiLU(),nn.Linear(48,1))

    def forward(self,x,cards,mask):
        h = self.action(torch.cat([x,self.cards(cards)],dim=-1))
        pool = (h*mask.unsqueeze(-1)).sum(1)/mask.sum(1,keepdim=True)
        return self.score(torch.cat([h,pool[:,None].expand_as(h)],-1)).squeeze(-1).masked_fill(~mask,-1e9)

class Guide:
    def __init__(self,path):
        ck = torch.load(path,weights_only=True)
        self.model = MenuPolicy(ck["width"]).eval()
        self.model.load_state_dict(ck["state"])

    @torch.inference_mode()
    def scores(self,obs,history,opening):
        x,ids = encode(obs,history,opening)
        return self.model(torch.from_numpy(x)[None],torch.from_numpy(ids)[None],
                          torch.ones((1,len(x)),dtype=torch.bool))[0].numpy()

