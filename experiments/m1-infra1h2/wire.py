"""The embedded JSON returned by the frozen tactical and selector schemas keeps null properties."""
from copy import deepcopy

def fill(row,names):
    return dict.fromkeys(names.split())|row

def card(row):
    return fill(row,"index id upgrade cost enchantment enchantment_amount affliction affliction_amount")

def action(row):
    a=fill(row,"index kind card target choice choice_zone potion cost preview star_cost energy_x star_x target_side target_type")
    if a["preview"] is not None:a["preview"]=fill(a["preview"],"damage_per_hit hits block draw")
    return a

def embedded(h):
    h=deepcopy(h)
    h.setdefault("nunchaku",None);h.setdefault("tuning_fork",None)
    for k in ("hand","discard","exhaust","deck"):h[k]=[card(c) for c in h[k]]
    h["actions"]=[action(a) for a in h["actions"]]
    return h
