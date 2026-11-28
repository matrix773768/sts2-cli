"""Exercise true contingency even when a whole-battle budget rarely selects a spliced policy."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"engine/HotSearch"))
from contingent import synthesize
from hot_produce import TurnPolicy

def program(style,indices,values,masses):
    edges=[dict(parent=0,view="root",index=3,node=1)]
    ends=[]
    for node,(view,index,value,mass) in enumerate(zip(("draw/A","draw/B"),indices,values,masses),2):
        edges.append(dict(parent=1,view=view,index=index,node=node))
        ends.append(dict(cursor=node,kind="Victory",mass=mass,evaluated=value))
    graph=dict(index=3,leaves=ends,policy=edges)
    return graph,dict(style=style,value=sum(v*m for v,m in zip(values,masses)))

def test():
    left=program("guard",[1,1],[8,0],[.25,.75])
    right=program("build",[2,2],[0,6],[.25,.75])
    (graph,option),=synthesize([left,right])
    assert option["value"]==6.5 and option["coverage"]==1
    for view,want in [("draw/A",1),("draw/B",2)]:
        policy=TurnPolicy(graph["policy"]);row={}
        assert policy.take(dict(view="root"),row)==3
        assert policy.take(dict(view=view),row)==want
    assert not list(synthesize([left,program("build",[2,2],[0,6],[.5,.5])]))

if __name__=="__main__":test()
