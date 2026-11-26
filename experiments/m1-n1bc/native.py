"""Independent native replay of a fixed systematic sample. Audit never calls a policy."""
from hashlib import sha256
import gzip
import json
from pathlib import Path
import argparse
from time import perf_counter

from arena import ROOT, CFG, Host, project
from loop_battle import Lane


def check(pred, native, job, row, base):
    from mechanics import POWER_IDS
    selected = []
    mechanism_checks = 0
    state = pred.request("pre0_start", spec=job[1], cap=128)["episode"]
    live = native.request("synthetic_start", spec=job[1])
    native.request("i1_begin")
    stamps, differences = 0, []
    for i, step in enumerate(row["steps"]):
        obs, a = step["observation"], step["action"]
        if obs != project(base, state["observation"]):
            raise ValueError(f"Predicted observation differs at {i}")
        if obs["decision"]["phase"] == "combat":
            rp = pred.request("i1_iid_prediction_roster")
            rn = native.request("i1_iid_native_roster")
            indices = {k:[rn[k].index(x) for x in rp[k]] for k in ("enemy","ally")}
            import targets
            targets.compare_menu(obs, live, indices)
            entities = [live["enemies"][s] for s in indices["enemy"]]
            actual_species = [e["name"].removesuffix(".name") for e in entities]
            stacks = sorted((owner, p["name"].removesuffix(".title"), p["amount"])
                            for owner, powers in enumerate([live.get("player_powers"), *[e.get("powers") for e in entities]], -1)
                            for p in powers or [] if p["name"].removesuffix(".title") in POWER_IDS)
            predicted = sorted((p["owner"],p["id"],p["amount"]) for p in obs["mechanism"]["stacks"])
            if actual_species != obs["mechanism"]["species"] or stacks != predicted:
                raise ValueError(f"Mechanism mismatch at {i}: {actual_species}, {stacks}, {predicted}")
            mechanism_checks += 1
            if [(e["hp"],e["block"]) for e in entities] != [(e["hp"],e["block"]) for e in obs["enemies"]]:
                raise ValueError(f"Enemy public state differs at {i}")
        else:
            import qualify_native
            d=obs["decision"]
            if live.get("decision") == "card_select" and (d["min"],d["max"]) != (live["min_select"],live["max_select"]):
                raise ValueError(f"position {i} effect {d.get('effect')} candidates {len(d['candidates'])}, predicted {d['min']}..{d['max']}, native {live['min_select']}..{live['max_select']}")
            qualify_native.compare_menu(obs,live)
        kind = a["kind"]
        args = {}
        if kind == "select_candidate":
            selected.append(a["choice"])
        else:
            if kind == "confirm_selection":
                kind, args = "select_cards", dict(indices=",".join(map(str,selected)))
                selected.clear()
            elif kind == "play_card":
                args = dict(card_index=a["card"])
                side = a["target_side"]
                if a["target"] is not None:
                    args["ally_index" if side=="ally" else "target_index"] = indices[side][a["target"]]
            live = native.request("action", action=kind, args=args)
        state = pred.request("i1_n2_step", position=i, index=a["index"])["episode"]
        if state.get("audit_stamp"):
            frame = native.request("i1_iib_native_stamp")
            locked = frame["state"][0]
            stamps += 1
            if sha256(locked["exact_continuation_state"].encode()).hexdigest() != state["audit_stamp"]:
                differences.append(i)
    frame = native.request("i1_iib_native_stamp")
    locked = frame["state"][0]
    if not frame["terminal"] and live["decision"] != "game_over":
        raise ValueError(f"Unresolved native terminal {live['decision']}")
    actual = {k:locked[k] for k in ("player_hp","player_max_hp","player_gold","player_potions")}
    t = row["terminal"]
    match = (actual["player_hp"],actual["player_max_hp"],actual["player_gold"],actual["player_potions"]) == (
        t["hp"],t["max_hp"],t["gold"],",".join(p or "-" for p in t["potions"]))
    win = live["decision"] != "game_over" and actual["player_hp"] > 0
    return dict(mechanism_checks=mechanism_checks, stamps=stamps, differing_stamps=differences, native=actual, decision=live["decision"],
                won=win, locked=frame["terminal"], terminal_match=match and win==(row["status"]=="predicted_win"))


def audit(out, arms, field_probe=False, choices=False, sample=False, ordinals=None):
    out.mkdir(parents=True, exist_ok=False)
    host = Host(out,ROOT/"logs/n1bc-host",CFG)
    results = []
    start = perf_counter()
    for arm in arms:
        plan=json.loads((arm/"manifest.json").read_bytes())
        jobs=[j for j in plan["jobs"] if j[2]=="report"]
        if (sample or arm.name.endswith("-24")) and ordinals is None:
            jobs=[j for j in jobs if (j[0]-192)%5==0]
        if field_probe:
            jobs=plan["jobs"][:32:2]
        if choices:
            jobs=[j for j in jobs if j[0] in (197,208,210)]
        if ordinals is not None:
            jobs=[j for j in jobs if j[0] in ordinals]
        for j in jobs:
            pred, native = Lane(host,0), Lane(host,1)
            with gzip.open(arm/f"{j[0]:03}.json.gz") as f:
                row = json.load(f)["row"]
            try:
                pred.open()
                native.open()
                result = check(pred,native,j,row,host.project)
            except (ValueError, RuntimeError, AssertionError, KeyError) as e:
                import traceback
                result = dict(error=type(e).__name__, detail=str(e), source=traceback.extract_tb(e.__traceback__)[-1].line)
            finally:
                pred.close()
                native.close()
            results.append(dict(arm=arm.name, ordinal=j[0], **result))
            (out/"audit.json").write_text(json.dumps(dict(seconds=perf_counter()-start, results=results),indent=2))


if __name__ == "__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("output",type=Path)
    cli.add_argument("arms",type=Path,nargs="+")
    cli.add_argument("--sample",action="store_true")
    cli.add_argument("--fields",action="store_true")
    cli.add_argument("--choices",action="store_true")
    cli.add_argument("--ordinals",nargs="+",type=int)
    args=cli.parse_args()
    audit(args.output,args.arms,args.fields,args.choices,args.sample,args.ordinals)
