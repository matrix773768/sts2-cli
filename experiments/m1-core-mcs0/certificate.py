"""Bottom-up checks over recorded laws. Unknown transitions never compare equal."""
from freeze import digest

def certificate(row):
    labels=row["labels"]
    leaves=row["leaves"]
    edges={(n,i):law for n,i,law in row["edges"]}
    best,policy,classes={},{},{}
    distinct={}
    for n in reversed(range(len(labels))):
        _,view,size=labels[str(n)]
        actions=[]
        comparable=[]
        for i in range(size):
            law=edges.get((n,i))
            if law is None:
                continue
            assert abs(sum(p for _,p in law)-1)<1e-7
            values=[]
            signatures=[]
            for k,p in law:
                assert p>0
                if isinstance(k,int):
                    assert k>n and labels[str(k)][0]==[n,i]
                    value=best.get(k)
                    label=classes.get(k)
                else:
                    value=leaves[k]["value"]
                    label=k
                if value is not None:values.append(p*value)
                if label is not None:signatures.append((label,p))
            if len(values)==len(law):comparable.append((sum(values),i))
            if len(signatures)==len(law):
                actions.append(digest(sorted(signatures)))
        if comparable:
            best[n],policy[n]=max(comparable,key=lambda x:x[0])
        if len(actions)==size:
            # Include the whole current observation as well as each bound action's law.
            classes[n]=digest([view,actions])
            distinct[classes[n]]=actions
    assert (0 in classes)==(row["curve"][-1]["exact"] is not None)
    if 0 in classes:
        assert abs(best[0]-row["curve"][-1]["exact"])<1e-6
    return dict(policy=policy,feasible=best.get(0),complete_histories=len(classes),
                classes=len(distinct),class_edges=sum(map(len,distinct.values())),
                response_classes=sum(len(set(a)) for a in distinct.values()))
