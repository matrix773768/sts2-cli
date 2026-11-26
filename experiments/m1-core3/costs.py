"""Production and deployment accounting; durations are summed per measured job."""
from experience import *
from value_net import *
from collections import Counter
import gzip,json
from statistics import median

def measure(out):
    torch.set_num_threads(1)
    states=[]
    for line in gzip.open(out/"fights0.gz"):
        states.extend(json.loads(line)["states"])
        if len(states)>=48:break
    states=states[:48];times={}
    for arm in ("simple","mechanism"):
        net=network(arm);net.load_state_dict(torch.load(out/(arm+".pt"),weights_only=True));net.eval()
        root=states[0]
        predict(net,arm,states,root)
        warm=[]
        for _ in range(25):
            t=perf_counter();predict(net,arm,states,root);warm.append(perf_counter()-t)
        times[arm]=median(warm)
    logs=ROOT/"logs"
    costs={name:read(logs/name/"seconds.json") for name in ["core3-pilot",*["core3-data"+str(i) for i in range(4)]]}
    audits=[json.load(gzip.open(p)) for p in sorted(out.glob("*audit.gz"))]
    costs.update({str(i)+"_"+a["split"]:a["seconds"] for i,a in enumerate(audits)})
    costs.update(fit=read(out/"fit.json")["seconds"],full_deploy=read(out/"deploy.json")["seconds"],
        draw_fixture=read(out/"draw.json")["seconds"],smoke=json.load(gzip.open(logs/"core3-smoke/audit.gz"))["seconds"],
        failure_replay_and_native=read(out/"diagnostics.json")["seconds"],first_failure_probe=15.37,
        failed_native_setup_estimate=10.0,evaluation=read(out/"results.json")["seconds"],test_process=5.46,core2_regression=5.58,core1r2_regression=5.53)
    rows=[json.loads(l) for f in out.glob("fights*.gz") for l in gzip.open(f)]
    return dict(costs=costs,summed_seconds=sum(costs.values()),warm_48_states_seconds=times,
        natural_actions=sum(r["actions"] for r in rows),paired_actions=sum(a["steps"] for a in audits),
        candidate_search_plays=sum(r["search"]["calls"] for a in audits for r in a["rows"]),
        full_deploy_search_plays=sum(r["calls"] for r in read(out/"deploy.json")["rows"]),
        candidate_world_proposals=sum(a["proposals"] for a in audits),
        updates_per_arm=50*math.ceil(read(out/"results.json")["labeled"]["train"]/64),
        presentations_per_arm=50*read(out/"results.json")["labeled"]["train"],gpu_seconds=0,
        scope="Host inner copies and child CPU not instrumented. Sum includes pilot and reruns; interpreter startup, short checks and editing excluded.")
if __name__=="__main__":
    out=Path(sys.argv[1]);(out/"ledger.json").write_text(json.dumps(measure(out),indent=2))
