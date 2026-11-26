"""Paired public draw exercise through C backup and observation-bound execution."""
from turn_value import *

def run(out,model_dir):
    out.mkdir(parents=True,exist_ok=False);t=perf_counter()
    arm=read(model_dir/"fit.json")["selected"];net=network(arm)
    net.load_state_dict(torch.load(model_dir/(arm+".pt"),weights_only=True));net.eval()
    host,_=setup(out);lane=Lane(host,0);rows=[]
    deck=["POMMEL_STRIKE"]+["DEFEND_IRONCLAD"]*4+["STRIKE_IRONCLAD","BLUDGEON","BLUDGEON"]
    spec=dict(schema=2,character="Ironclad",ascension=0,act=1,act_variant="OVERGROWTH",encounter="FUZZY_WURM_CRAWLER_WEAK",
        seed="CORE1RFIX",hp=80,max_hp=80,deck=[dict(id=c,upgrade=0) for c in deck],relics=[],potions=[])
    for order in [list(range(8)),[0,1,2,3,4,6,7,5]]:
        lane.open()
        st=lane.request("pre0_start",spec=spec,cap=128,sv1_fixture=dict(n4_order=order,enemy_hp=15))["episode"]
        h=host.project(st["observation"]);g,ch,opts,metrics=compile_turn(lane,h,[],net,arm)
        idx=next(i for i,e in enumerate(g["nodes"][0]["edges"]) if e["input"]["card"]==0)
        chance=g["nodes"][g["nodes"][0]["edges"][idx]["to"]]
        end,history,reason=execute(lane,st,g,ch,idx)
        rows.append(dict(root=digest(h),options=opts,law={e["input"]:e["probability"] for e in chance["edges"]},
                         reason=reason,status=end["status"],actions=len(history),stats=metrics))
        lane.reset()
    host.close();(out/"draw.json").write_text(json.dumps(dict(rows=rows,seconds=perf_counter()-t),indent=2))
if __name__=="__main__":run(Path(sys.argv[1]),Path(sys.argv[2]))
