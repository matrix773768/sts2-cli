"""Evaluate all weights through the same 5C full-turn planner."""
import sys
from panel5e import E,OUT
from battle5d import configure,run
from deploy5b import load_net
from complete import Planner
def setup_arm(out,arm):
    if arm in ("V2","V2low","V3","G2","G2search"):return configure(out,arm)
    if arm.startswith("anchor-"):
        from incumbent5e import setup
        return setup(out,arm)
    host,g2,_,_=configure(out,"V2")
    net=load_net(E/(arm+".pt"),arm)
    return host,g2,net,Planner(net)
if __name__=="__main__":
    run(*sys.argv[1:3],*map(int,sys.argv[3:]),evidence=E,logs=OUT,setup_arm=setup_arm)
