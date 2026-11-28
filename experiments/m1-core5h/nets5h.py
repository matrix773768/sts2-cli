"""One induced token interaction before the frozen pooling operation."""
import math
import torch
from torch import nn
from semantic import Value

class Interaction(nn.Module):
    def __init__(self):
        super().__init__()
        self.seeds=nn.Parameter(torch.randn(4,16)/4)
        self.key=nn.Linear(32,16)
        self.value=nn.Linear(32,16)
        self.query=nn.Linear(32,16)
        self.out=nn.Linear(16,32)
        nn.init.zeros_(self.out.weight)
        nn.init.zeros_(self.out.bias)

    def forward(self,v,mask):
        logits=self.key(v)@self.seeds.T/4
        weights=logits.masked_fill(~mask.unsqueeze(-1),-1e6).softmax(1)
        slots=weights.transpose(1,2)@self.value(v)
        context=(self.query(v)@slots.transpose(1,2)/4).softmax(-1)@slots
        return v+self.out(context)

class Local(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers=nn.Sequential(nn.Linear(32,32),nn.SiLU(),nn.Linear(32,32))
        nn.init.zeros_(self.layers[-1].weight)
        nn.init.zeros_(self.layers[-1].bias)
    def forward(self,v,mask):return v+self.layers(v)

class Extended(Value):
    def __init__(self,kind):
        super().__init__()
        self.transform=Interaction() if kind=="interact" else Local()
    def forward(self,g,x,m):
        v=self.transform(self.entity(x),m)
        w=self.attention(v).masked_fill(~m.unsqueeze(-1),-1e6).softmax(1)
        pool=torch.bmm(w.transpose(1,2),v).flatten(1)
        return self.head(torch.cat((g,pool,(v*m.unsqueeze(-1)).sum(1)/m.sum(1,keepdim=True).sqrt()),1))

def network(kind):
    if kind=="pool":return Value()
    if kind not in ("interact","local"):raise ValueError(kind)
    return Extended(kind)
