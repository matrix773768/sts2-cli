"""Finite old-host comparisons at legal stopping points, before enemy settlement."""
from collections import Counter
from itertools import combinations_with_replacement
from freeze import H, gz, digest, save

def audit(graph):
    nodes = graph["nodes"]
    def state(n):
        return digest([n["state"],n["belief"]])
    return {state(n) for n in nodes if n["end"] is not None}

def finite(graph):
    nodes = graph["nodes"]
    sizes = {}
    def visit(i):
        n=nodes[i]
        assert n["kind"]=="decision" and n["end"] is not None
        outgoing = {e["input"]["index"]:e for e in n["edges"]}
        legal = {a["index"] for a in n["state"]["actions"] if a["kind"]!="end_turn"}
        assert outgoing.keys()==legal
        transitions=[]
        for idx,e in sorted(outgoing.items()):
            assert e["probability"] is None
            transitions.append((idx,visit(e["to"])))
        key=digest([n["state"],n["belief"],transitions])
        sizes[key]=1
        return key
    visit(0)
    def menu(i):
        n=nodes[i]
        for e in n["edges"]:
            a=e["input"]
            c=n["state"]["hand"][a["card"]]
            yield (c["id"],c["upgrade"],a["target"] if a["target"] is not None else -1),e["to"]
    def key(i):
        return digest([nodes[i]["state"],nodes[i]["belief"]])
    visited=[]
    def ordered(i,last):
        visited.append(key(i))
        # Use a stable token for equal copies, preserve enemy slot.
        for tag,j in dict(menu(i)).items():
            if last is None or tag>=last:
                ordered(j,tag)
    ordered(0,None)
    tags=sorted(dict(menu(0)))
    allocations=set()
    attempts=0
    for count in range(nodes[0]["state"]["energy"]+1):
        for allocation in combinations_with_replacement(tags,count):
            i=0
            attempts+=1
            for tag in allocation:
                i=dict(menu(i)).get(tag)
                if i is None:break
            if i is not None:allocations.add(key(i))
    truth=audit(graph)
    assert set(visited)==allocations and allocations<=truth
    return dict(raw=len(nodes),bisimulation=len(sizes),ordered_paths=len(visited),allocation_trials=attempts,
                missing=len(truth-allocations),missing_example=next(iter(sorted(truth-allocations)),None),allocation_outcomes=len(allocations),set_hash=digest(sorted(truth)))

def main():
    rows={}
    for name,r in gz(H.parent/"m1-core1r2/evidence/fixtures.json.gz")["rows"].items():
        graphs=r["graphs"]
        full=audit(graphs["tree"])
        reduced=audit(graphs["reduced"])
        rows[name]=dict(raw_stops=len(full),reduced_stops=len(reduced),missing=len(full-reduced),
                        extra=len(reduced-full),calls={k:g["calls"] for k,g in graphs.items()},
                        kinds=dict(Counter(n["kind"] for n in graphs["tree"]["nodes"])))
        if name in ("basic","multi_target","upgrade"):
            rows[name]["finite"]=finite(graphs["tree"])
    save("fixtures.json",rows)

if __name__=="__main__":main()
