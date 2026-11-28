"""Splice closed turn programs after the same first action and public observation."""
from collections import defaultdict
from math import isclose
from models import return_law


def split(graph):
    edges=graph["policy"]
    root,=[e for e in edges if not e["parent"]]
    branch={root["node"]:None}
    children=defaultdict(list)
    leaves=defaultdict(list)
    for edge in edges:
        if not edge["parent"]:
            continue
        view=edge["view"] if edge["parent"]==root["node"] else branch[edge["parent"]]
        branch[edge["node"]]=view
        children[view].append(edge)
    for leaf in graph["leaves"]:
        leaves[branch[leaf["cursor"]]].append(leaf)
    return root,children,leaves


def synthesize(groups):
    """Keep the physical probability of every leaf. Reject incompatible next-observation laws."""
    by_first=defaultdict(list)
    for graph,option in groups:
        if option["value"] is not None:
            by_first[graph["index"]].append((graph,option))
    for first,family in by_first.items():
        if len(family)<2:
            continue
        trees=[split(graph) for graph,_ in family]
        root,_,base=trees[0]
        views=set(base)-{None}
        if len(views)<2:
            continue
        def mass(rows):return sum(leaf["mass"] for leaf in rows)
        direct=return_law({"leaves":base.get(None,[])})
        if any(r!=root or set(leaves)!=set(base) or
               return_law({"leaves":leaves.get(None,[])})!=direct or
               any(not isclose(mass(leaves[v]),mass(base[v]),rel_tol=1e-12,abs_tol=0) for v in views)
               for r,_,leaves in trees[1:]):
            continue
        edges=[root];output=list(base.get(None,[]));sources={}
        for view in sorted(views):
            def expectation(tree):
                return sum(x["mass"]*x["evaluated"] for x in tree[2][view])
            best=max(range(len(trees)),key=lambda i:expectation(trees[i]))
            _,children,leaves=trees[best]
            sources[view]=family[best][1]["style"]
            renumber={root["node"]:root["node"]}
            for edge in children[view]:
                node=len(edges)+1
                edges.append(edge|dict(parent=renumber[edge["parent"]],node=node))
                renumber[edge["node"]]=node
            output.extend(x|dict(cursor=renumber[x["cursor"]]) for x in leaves[view])
        if len(set(sources.values()))<2:
            continue
        value=sum(x["mass"]*x["evaluated"] for x in output)
        if value<=max(option["value"] for _,option in family)+1e-9:
            continue
        if abs(mass(output)-1)>1e-8:
            raise ValueError("composed policy mass")
        graph=dict(index=first,policy=edges,leaves=output,steps=0,chances=0,choices=0,gaps={})
        option={k:v for k,v in graph.items() if k not in ("policy","leaves")}
        yield graph,option|dict(coverage=mass(output),leaves=len(output),value=value,style="conditional",sources=sources)
