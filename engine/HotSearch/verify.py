"""Check probabilities, denominators, immutable inputs and the released admission sets."""
import math
from release import E, ROOT, STAGES, STRICT_WORLDS, read, rows, sha


def require(value,message):
    if not value:raise ValueError(message)


def verify():
    hashes=read(E/"sha256.json")
    for name,digest in hashes.items():require(sha(E/name)==digest,name)
    summary=read(E/"summary.json")
    cohorts={k:rows(E/(k+".jsonl.gz")) for k in STAGES}
    n=cohorts["natural"];native={r["i"]:r for r in cohorts["native"]}
    panel=read(ROOT/"experiments/m1-infra0/panel.json")
    frozen=set(i for group in panel["natural"].values() for i in group)
    require(all(len({r["i"] for r in cohorts[k]})==len(cohorts[k]) for k in cohorts),"duplicate root")
    require(len(frozen)==96 and all({r["i"] for r in cohorts[k]}==frozen and len(cohorts[k])==96 for k in ("natural","strict","feedback","g2","native","frozen")),"natural panel drift")
    expected=set(panel["pairs"]["natural_reuse"]+panel["pairs"]["two_continuations"])
    require({r["i"] for r in cohorts["pairs"]}==expected,"paired roots")
    for r in n+cohorts["strict"]+cohorts["feedback"]+cohorts["g2"]:
        if r["status"]=="failed":require(r["terminal"] is None and r.get("reason"),"failed root lost")
        else:require(r["terminal"] is not None and r["actual_steps"]==len(r["trace"])+len(r["choices"]),"completed trajectory")
        for c in r["states"]:
            require(c["setup"]["stage"]=="before_initial_draw" and sum(c["belief"]["counts"].values())==c["draw_count"],"invalid C")
        for q in r["queries"]:
            for o in [q["reference_law"],*q["options"]]:
                require(abs(1-o["coverage"]-sum(o["gaps"].values()))<1e-8,"unaccounted probability")
                require((o["value"] is None)==bool(o["gaps"]),"incomplete backed-up law")
            if "law" in q:
                require(abs(sum(q["law"].values())-1)<1e-8,"committed support")
                if "matched" in q:require(q["matched"]==(q["observed"] in q["law"]),"realized support")
    reviewed={r["i"] for r in rows(E/"natural-reviewed.jsonl.gz")}
    require(reviewed=={r["i"] for r in cohorts["strict"] if r["terminal"] and native[r["i"]]["status"]=="matched"},"reviewed dataset")
    for split,limit in (("world-train",128),("world-dev",48)):
        require({r["i"] for r in cohorts[split]}==set(range(limit)),split)
    require(not ({r["family"] for r in cohorts["world-train"]}&{r["family"] for r in cohorts["world-dev"]}),"train/dev overlap")
    for base,strict in zip(("world-train","world-dev","123","pairs"),STRICT_WORLDS):
        require([r["i"] for r in cohorts[base]]==[r["i"] for r in cohorts[strict]],strict+" panel")
    for group in ("world-train","world-dev","123","pairs",*STRICT_WORLDS):
        for r in cohorts[group]:
            for p in r["plans"]:
                require(all(abs(sum(p[k].values())-1)<1e-8 for k in ("public_law","law")),"plan mass")
            if r["status"]!="matched":continue
            require(len(r["plans"])==2 and len(r["worlds"])==r["world_count"] and len(r["natural_pair"])==2,"pair count")
            if r["world_count"]:require(r["invariant"],"hidden world altered policy")
            require(len({w["seed"] for w in r["worlds"]})==len(r["worlds"]),"duplicate world seed")
            for pair in [r["natural_pair"],*[w["outcomes"] for w in r["worlds"]]]:
                require(len(pair)==2,"missing sibling")
                for plan,side in zip(r["plans"],pair):
                    require(side["observed"] in plan["law"] and side["public_key"] in plan["public_law"] and math.isfinite(side["utility"]),"conditional return")
    estimate=next(r for r in cohorts["world-train"] if r["i"]==123)
    audit,=cohorts["123"]
    strict_audit,=cohorts["strict123"]
    require(strict_audit["status"]=="matched" and audit["plans"]==strict_audit["plans"],"strict 123 intervention")
    require(audit["source_index"]==87 and estimate["public"]==audit["public"] and estimate["plans"]==audit["plans"],"123 changed")
    require(not ({w["seed"] for w in estimate["worlds"]}&{w["seed"] for w in audit["worlds"]}),"audit sampling overlap")
    require(all(m["exit"]==0 for m in summary["campaign"]) and sum(m["seconds"] for m in summary["campaign"])<7200,"worker ledger")
    require(summary["build"]["game"]==sha(ROOT/"lib/sts2.dll"),"game identity")
    require(summary["rebuilt"]["identical"]==len(cohorts["strict"]),"rebuild regression")
    print("Verified release hashes, complete panels, conditioning, outcomes and admission sets.")


if __name__=="__main__":verify()
