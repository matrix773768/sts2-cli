"""Pre-confirmation secondary ablation: deploy the unweighted behavior-cloning control directly."""
from common6 import *
from search6 import Actor
from policy6 import Guide

class Clone(Actor):
    def __init__(self):
        super().__init__("direct")
        self.frozen=read(E/"clone-selection.json")
        weights=E/(self.frozen["name"]+".pt")
        assert sha(weights)==self.frozen["weight"]
        self.guide=Guide(weights)

    def identity(self,arm,limit,margin=0.):
        parent=super().identity(arm,limit,margin)
        body={k:v for k,v in parent.items() if k!="id"}|dict(arm="clone",weight=self.frozen["weight"],adapter=sha(HERE/"clone6.py"))
        return body|dict(id=digest(body))

def freeze():
    assert not (E/"selection.json").exists() and not list(E.glob("confirm-*.json"))
    arm=max((f"behavior-{s}" for s in (6119,6233)),key=lambda k:read(E/(k+".json"))["score"])
    save(E/"clone-selection.json",dict(name=arm,weight=sha(E/(arm+".pt")),panel_sha=sha(E/"confirm.gz"),
         role="Secondary direct behavior-cloning control, committed after offline/development observations and before any confirmation. Same 320 families, no promotion test."))
if __name__=="__main__":freeze()

