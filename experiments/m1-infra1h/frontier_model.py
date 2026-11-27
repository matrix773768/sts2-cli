"""The host owns the FIFO and route graph. Frozen Python models retain their original inputs."""
import search5
import os

checker=None
exact=None
guarded=None

def reference(lane,h,past,g2,limit=48,observe=None):
    if observe is not None:return search5.reference(lane,h,past,g2,limit,observe)
    controller=search5.prepared(g2,h,past)
    if exact:exact.bind(controller)
    def choose(obs,history):
        action=int(controller.score([(obs,history)])[0][0].argmax())
        return action,g2.encoder.update(history,obs,obs["actions"][action])
    first,history=choose(h,controller.history)
    histories={0:history}
    reply=lane.request("i1_infra1h_frontier",first=first,past=len(past),limit=limit,actions=[])
    while not reply["done"]:
        if guarded:
            ready=[(lane.host.project(r["state"]),histories[r["history"]]) for r in reply["decisions"]]
            actions=guarded.choose(controller,ready)
            for r,(obs,hist),action in zip(reply["decisions"],ready,actions,strict=True):
                histories[r["token"]]=g2.encoder.update(hist,obs,obs["actions"][action])
            reply=lane.request("i1_infra1h_frontier",actions=actions)
            continue
        actions=[]
        inputs=[];scores=[]
        for r in reply["decisions"]:
            obs=lane.host.project(r["state"])
            history=histories[r["history"]]
            if checker:
                inp=(obs,history);inputs.append(inp)
                score=controller.score([inp])[0];scores.append(score)
                action=int(score[0].argmax())
                histories[r["token"]]=g2.encoder.update(history,obs,obs["actions"][action])
            else:action,histories[r["token"]]=choose(obs,history)
            actions.append(action)
        if checker:checker.compare(controller,inputs,scores)
        reply=lane.request("i1_infra1h_frontier",actions=actions)
    leaves=reply["leaves"]
    for leaf in leaves:leaf["probability"]=float(leaf["probability"])
    if abs(sum(r["probability"] for r in leaves)-1)>1e-8:raise ValueError("Reference lost mass")
    return leaves,reply["calls"],first

def install(task,battle):
    global checker,exact,guarded
    if task["variant"].endswith("-g2"):
        from guarded_model import Guarded
        guarded=Guarded()
    if task['variant'].startswith(('h-kernel4','h-kernel5','h-kernel6')):
        from exact_model import ExactModel
        exact=ExactModel()
    if os.environ.get("INFRA1H_MODEL_CHECK")=="1":
        from model_check import Check
        checker=Check()
    import complete
    complete.reference=reference
    if task["variant"].startswith("h-kernel"):
        import conditional_model
        conditional_model.install(memo=task["variant"].startswith(("h-kernel5","h-kernel6")))
    outputs=[m for m in (checker,exact,guarded) if m]
    if task["variant"].startswith(("h-kernel5","h-kernel6")):outputs.append(conditional_model)
    if outputs:
        class Reports:
            def save(self,folder):
                for output in outputs:output.save(folder)
        return Reports()
