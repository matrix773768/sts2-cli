"""H5 public history-tree enumeration. No private checkpoint is used for branching."""
import argparse, gzip, json, sys, time
from collections import Counter, deque
from pathlib import Path
from freeze import H, E, CORE, digest, sources, read

sys.path.insert(0,str(H.parent/"m1-core6b2"))
from branch import Actor, portfolio, s
from common6 import public_b, choice_b, torch
torch.set_num_threads(1)

def recover(host, model, root):
    st = host.call("open",spec=root["spec"])
    hist = model.g2.encoder.initial_history()
    for step in [*root["steps"],dict(observation=root["root"], index=None)]:
        o = step["observation"]
        assert all(st[k]==v for k,v in o.items())
        assert list(st["facts"]["belief"]["counts"])==list(o["facts"]["belief"]["counts"])
        i = step["index"]
        if i is None:
            return st, hist
        menu = choice_b(st["facts"],st) if st["status"]=="choice" else public_b(st["facts"])
        hist = model.advance(hist,menu,menu["actions"][i])
        st = host.call("step",index=i)

def arms(host, models, st, hist, opening):
    result = {}
    for mode,m in models.items():
        menu = public_b(st["facts"])
        rank = m.rank(menu,hist,opening)
        groups = portfolio(host,m,rank,opening,"tactical",32)
        ref = host.reference(rank[0],32,m,menu,hist,opening)
        options = [(ref,m.backup([ref],opening)[0]|dict(style="ref")),*groups]
        best = 0 if ref["gaps"] else max((i for i,(_,q) in enumerate(options) if q["value"] is not None),
                                         key=lambda i:options[i][1]["value"])
        result[mode] = dict(best=best,options=[dict(q=q,program=digest(g["policy"])) for g,q in options])
    return result

class Tree:
    def __init__(self, st):
        self.nodes = {}
        self.todo = deque()
        self.labels = {}
        self.edges = {}
        self.tried = set()
        self.leaves = {}
        self.count = Counter()
        self.root = self.menu("",st["view"],len(st["facts"]["actions"]))
        self.witness = None
        self.probes = []

    def menu(self, parent, view, size):
        key = (parent,view)
        if key not in self.nodes:
            ident = len(self.nodes)
            self.nodes[key] = ident
            self.labels[ident] = (parent,view,size)
            self.todo.extend((ident,i) for i in range(size))
        n = self.nodes[key]
        assert self.labels[n][2]==size
        return n

    def probe(self,host,model,opening,target,limit,native=None):
        # A path is a sequence of choices bound to the whole public observation history.
        path = {}
        action = target
        while action:
            n,i = action
            path[n] = i
            action = self.labels[n][0]
        rootaction = (self.root,path[self.root])
        group = {1:rootaction}
        memories = {0:rootaction}
        intern = {rootaction:1}
        row = host.engine.send(dict(op="search",indices=[rootaction[1]],limit=limit,g2=True))
        while row["type"]=="g2":
            f,p = row["facts"],row["prompt"]
            parent = memories[row["parent"]]
            size = len(p["options"] if p else f["actions"])
            n = self.menu(parent,digest([f,p]),size)
            idx = path[n] if n in path else (0 if p else next(a["index"] for a in f["actions"] if a["kind"]=="EndTurn"))
            action = (n,idx)
            memories[row["ticket"]] = action
            if action not in intern:
                intern[action] = len(intern)+1
                group[intern[action]] = action
            row = host.engine.send(dict(op="g2",ticket=row["ticket"],index=idx))
        if not row["ok"]:
            raise RuntimeError(row["reason"])
        g = row["result"][0]
        assert len(g["policy"])==len(group) or (not g["policy"] and g["gaps"])
        for e in g["policy"]:
            n,i = group[e["node"]]
            if native is not None:
                assert native.setdefault(n,e["view"])==e["view"]
            assert e["index"]==i and (group[e["parent"]]==self.labels[n][0] if e["parent"] else e["view"]==self.labels[n][1])
        self.count.update({k:g[k] for k in ("steps","chances","choices")})
        q = model.backup([g],opening,annotate=True)[0]
        self.probes.append(dict(target=target,steps=g["steps"],gaps=g["gaps"],value=q["value"]))
        if g["gaps"]:
            return
        if self.witness is None or q["value"]>self.witness["value"]:
            self.witness = dict(value=q["value"],policy=g["policy"])
        assert target in intern
        # Recover one-step laws from a closed whole-program law. Each cursor is a
        # distinct observation history; its mass includes all descendant leaves.
        laws = {i:Counter() for i in group}
        for leaf in g["leaves"]:
            raw = {k:v for k,v in leaf.items() if k not in ("evaluated","cursor","mass")}
            key = digest(raw)
            if key in self.leaves:
                assert abs(self.leaves[key]["value"]-leaf["evaluated"])<1e-4
            else:
                self.leaves[key] = dict(kind=leaf["kind"],value=leaf["evaluated"])
            laws[leaf["cursor"]][key] += leaf["mass"]
        for cur in reversed(range(1,len(group)+1)):
            action = group[cur]
            parent = self.labels[action[0]][0]
            mass = sum(laws[cur].values())
            assert mass>0
            trans = {k:v/mass for k,v in laws[cur].items()}
            if action in self.edges:
                old = self.edges[action]
                assert old.keys()==trans.keys() and all(abs(old[k]-v)<1e-7 for k,v in trans.items())
            self.edges[action] = trans
            if parent:
                laws[intern[parent]][action[0]] += mass
            else:
                assert abs(mass-1)<1e-7

    def summary(self):
        values = {}
        for n in reversed(range(len(self.labels))):
            qs = []
            for i in range(self.labels[n][2]):
                t = self.edges.get((n,i))
                if t is None or any(isinstance(k,int) and values[k] is None for k in t):
                    break
                qs.append(sum(p*(values[k] if isinstance(k,int) else self.leaves[k]["value"]) for k,p in t.items()))
            values[n] = max(qs) if len(qs)==self.labels[n][2] else None
        return dict(histories=len(values),legal=sum(x[2] for x in self.labels.values()),known_edges=len(self.edges),
                    exact=values[0],witness=self.witness and self.witness["value"],**self.count)

def run(root,host,models,budgets,wall,physical):
    start = time.perf_counter()
    st,hist = recover(host,models["v2"],root)
    opening = {k:root["spec"][k] for k in ("hp","max_hp")}
    s4 = arms(host,models,st,hist,opening)
    tree = Tree(st)
    rows = []
    tick = time.perf_counter()
    before = models["v2"].work.copy()
    for budget in budgets:
        while tree.todo and len(tree.probes)<budget and time.perf_counter()-tick<wall:
            action = tree.todo.popleft()
            if action in tree.edges or action in tree.tried:
                continue
            tree.tried.add(action)
            tree.probe(host,models["v2"],opening,action,physical)
        rows.append(tree.summary()|dict(budget=budget,probes=len(tree.probes),seconds=time.perf_counter()-tick))
    return dict(arms=s4,curve=rows,seconds=time.perf_counter()-start,replayed=len(root["steps"]),
                time_cap=time.perf_counter()-tick>=wall,host=host.call("metrics"),work={k:v-before.get(k,0) for k,v in models["v2"].work.items()},
                probes=tree.probes,witness=tree.witness,labels=tree.labels,leaves=tree.leaves,
                edges=[[n,i,list(t.items())] for (n,i),t in tree.edges.items()])

def main():
    p=argparse.ArgumentParser()
    p.add_argument("phase",choices=["pilot","panel"])
    args=p.parse_args()
    cfg=read(H/(args.phase+".json"))
    dest=E/args.phase
    dest.mkdir(exist_ok=True)
    start=time.perf_counter()
    models={mode:Actor(mode) for mode in ("v2","low","general")}
    roots=sources()
    host=s.SearchClient(CORE/"logs/core-mcs0"/args.phase,False)
    try:
        for id_ in cfg["ids"]:
            if time.perf_counter()-start>cfg["campaign_seconds"]:
                break
            tick=time.perf_counter()
            try:
                row=run(roots[id_],host,models,cfg["budgets"],cfg["wall"],cfg["physical"])
            except (RuntimeError,OSError,ValueError,TimeoutError,AssertionError) as exc:
                row=dict(error=repr(exc),seconds=time.perf_counter()-tick)
                host.restart()
            (dest/(id_+".gz")).write_bytes(gzip.compress(json.dumps(row,separators=(",",":"),allow_nan=False).encode(),mtime=0))
            print(id_,row.get("curve",[row.get("error")])[-1],flush=True)
    finally:
        host.close()
        (dest/"seconds.json").write_text(json.dumps(time.perf_counter()-start))

if __name__=="__main__":
    main()
