"""Force two public menu alternatives, then use the same exploratory G2 continuation."""
from pathlib import Path
import gzip
import json
import random
import sys
from time import perf_counter

from arena import CFG, PARENT, ROOT, Controller, Host, Policy, collect, digest, load, manifest, project
from learn import restore
from value import payoff, torch


class FirstAction(Controller):
    def act(self, public, lane, position):
        if position:
            return super().act(public,lane,position)
        self.initial_hp, self.initial_max = public["hp"], public["max_hp"]
        scores = self.score([(public,self.history)])[0][0]
        first = int(scores.argmax())
        alternatives = [i for i,a in enumerate(public["actions"]) if i != first]
        index = random.Random(self.job).choice(alternatives) if self.alternate and alternatives else first
        self.scores = scores.tolist()
        self.history = self.model.encoder.update(self.history, public, public["actions"][index])
        return index, 1., "forced_public_pair"


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    start=perf_counter()
    host=Host(out,ROOT/"logs/n1bc-host",CFG)
    old=host.project
    host.project=lambda wire: project(old,wire)
    _,meta=load(PARENT)
    teacher=Policy(PARENT,meta["deployment"],0,.1,host.version,CFG)
    models={}
    for name in ("base17","mech17","base29","mech29"):
        model=Policy(PARENT,meta["deployment"],0,0.,host.version,CFG)
        model.net,model.encoder,model.slot=restore(ROOT/f"logs/n1bc-{name}/model.pt")
        models[name]=model
    plan=manifest()
    report=[]
    try:
        for j in plan["jobs"][192:]:
            data = []
            for alt in (False,True):
                c=FirstAction(teacher,host.project,lambda rows:next(teacher.forward([(rows,)])),random.Random(j[0]))
                c.job,c.alternate=j[0],alt
                item=collect(host.lane(),c,teacher.definition | dict(forced_alternative=alt),plan,j,digest([j[0],alt]))
                with gzip.open(out/f"{j[0]}-{int(alt)}.json.gz","wt",encoding="utf-8") as f:
                    json.dump(item,f,separators=(",",":"))
                data.append(item["row"])
            if not all(r["complete"] for r in data):
                report.append(dict(ordinal=j[0],status=[r["status"] for r in data]))
                continue
            obs=data[0]["steps"][0]["observation"]
            assert data[1]["steps"][0]["observation"]==obs
            actions=[r["steps"][0]["action"]["index"] for r in data]
            values=[-50. if r["status"]=="death" else payoff(torch.tensor(obs["hp"]-r["terminal"]["hp"]),
                    torch.tensor(obs["max_hp"])).item() for r in data]
            predictions={}
            for name,model in {"frozen":teacher,**models}.items():
                c=Controller(model,host.project,lambda rows:next(model.forward([(rows,)])),random.Random(0))
                c.initial_hp,c.initial_max=obs["hp"],obs["max_hp"]
                scores=c.score([(obs,c.history)])[0][0]
                predictions[name]=scores[actions].tolist()
            report.append(dict(ordinal=j[0],actions=actions,utility=values,predictions=predictions))
    finally:
        host.close()
        (out/"ranking.json").write_text(json.dumps(dict(seconds=perf_counter()-start,roots=report),indent=2))


if __name__=="__main__":
    run(Path(sys.argv[1]))
