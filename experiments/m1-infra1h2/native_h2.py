"""Replay to each first divergence in the archived ordinal order on both engines."""
import gzip
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "m1-core5d"))
import battle5d
from complete import host_at
from panel5d import cohort

def inputs():
    worker = ROOT / "logs/infra0-runs/infra1h-E-natural-h-kernel5/worker-0"
    assert json.loads((worker / "verification.json").read_bytes())["equal"]
    artifact = json.loads((worker / "worker.json").read_bytes())["closed"]["file"]
    with gzip.open(worker / "evidence" / artifact) as f:
        rows = list(map(json.loads, f))
    with gzip.open(HERE.parent / "m1-core5d/evidence/panel.gz") as f:
        return rows, json.load(f)["train"]

def run():
    rows, panel = inputs()
    stops = json.loads((HERE.parent / "m1-infra1h/evidence/private-kernel6.json").read_bytes())
    log = ROOT / "logs/infra1h2/native"
    results = []
    stops += [dict(stage="stop",root=92,steps=21,detail="H2/early_terminal")]
    for e in stops:
        if e["stage"] != "stop":
            continue
        ordinal, n = e["root"], e["steps"]
        row = rows[ordinal]
        spec = panel[row["i"]]["spec"]
        hosts = []
        lanes = []
        result = dict(ordinal=ordinal, panel=row["i"], reason=e["detail"], step=n, encounter=spec["encounter"])
        results.append(result)
        try:
            for name, build in [("pred","infra1h-5d-kernel6"), ("native","core5c-host")]:
                out = log / f"{ordinal}-{n}" / name
                out.mkdir(parents=True, exist_ok=True)
                hosts.append(host_at(out, ROOT / "logs" / build))
                lanes.append(battle5d.Lane(hosts[-1],0))
            pred, native = lanes
            st = cohort.start(pred, spec)
            native.open()
            live = native.request("synthetic_start",spec=spec)
            native.request("i1_begin")
            selected = []
            recent = []
            for step, (turn,index) in enumerate(row["trace"][:n],1):
                h = st["observation"]
                a = h["actions"][index]
                kind = a["kind"]
                args = {}
                recent.append(dict(step=step,kind=kind,card=h["hand"][a["card"]]["id"] if a.get("card") is not None else None,
                    selection=h["decision"].get("selected"),effect=h["decision"].get("effect"),native_phase=live["decision"]))
                if h["decision"]["phase"]=="choice":
                    assert live["decision"]=="card_select"
                    assert [(c["id"],c["upgrade"]) for c in h["decision"]["candidates"]]==[
                        (c["id"].split(".")[-1],int(c.get("upgraded",False))) for c in live["cards"]]
                if kind == "select_candidate":
                    selected.append(a["choice"])
                else:
                    if kind == "confirm_selection":
                        kind = "select_cards"
                        args["indices"] = ",".join(map(str, selected))
                        selected.clear()
                    if kind == "play_card":
                        slot = a["card"]
                        assert live["hand"][slot]["id"].split(".")[-1] == h["hand"][slot]["id"]
                        args["card_index"] = slot
                        if a.get("target") is not None:
                            side = a.get("target_side", "enemy")
                            rp = pred.request("i1_iid_prediction_roster")[side]
                            rn = native.request("i1_iid_native_roster")[side]
                            args["ally_index" if side=="ally" else "target_index"] = rn.index(rp[a["target"]])
                    live = native.request("action",action=kind,args=args)
                st = cohort.step(pred, st,index)
                result["reached"] = step
            result["last_actions"]=recent[-5:]
            stamp = native.request("i1_iib_native_stamp")["state"][0]
            obs = st.get("observation") or st.get("terminal_observation") or {}
            result.update(action=a, played=h["hand"][a["card"]]["id"] if "card" in a and a["card"] is not None else None,
                frozen={k:obs.get(k) for k in ("hp","max_hp","decision","discard","hand")},
                native={k:v for k,v in live.items() if k in ("decision","player","cards","discard_pile","discard_count","hand","hp","max_hp","enemies")},
                stamp={k:v for k,v in stamp.items() if k in ("player_hp","player_max_hp","player_gold","discard_count","discard_pile")})
            if "player_ordered_piles" in stamp:
                piles=stamp["player_ordered_piles"].split(";")
                result["native_discard"]=next((z[2:] for z in piles if z.startswith("C=")),None)
            if ordinal==5:
                (log/"stamp.json").write_text(json.dumps(stamp,default=str))
            if ordinal==5 or ordinal==13:
                (log/f"wire-{ordinal}.json").write_text(json.dumps(h))
        except (RuntimeError,KeyError,ValueError,IndexError,AssertionError) as exc:
            result["error"] = repr(exc)
        finally:
            for lane in lanes: lane.close()
            for host in hosts: host.close()
    (HERE/"evidence/native.json").write_text(json.dumps(results,separators=(",",":")))
if __name__=="__main__": run()
