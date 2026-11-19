from collections import Counter, defaultdict

from run_factorial import HERE, n2b, manifest, read


def test_frozen_factorial_and_nonoverlap_with_history():
    frozen = manifest()
    cells = defaultdict(dict)
    older = read(HERE.parent/"m1-n2c/manifest.json")["cases"]
    old_seeds = {i["case"]["spec"]["seed"] for i in older}
    assert len(frozen["cases"]) == 64
    for item in frozen["cases"]:
        c=item["case"]
        assert c["spec_sha256"] == n2b.stamp(c["spec"])
        assert c["spec"]["seed"] not in old_seeds
        cells[c["source_id"]][c["seed_index"],c["deck_index"]] = c
    assert len(cells)==16
    for group in cells.values():
        assert set(group)=={(0,0),(0,1),(1,0),(1,1)}
        assert len({c["diagnostic_split"] for c in group.values()})==1
        for s in (0,1):
            a,b=(group[s,d]["spec"] for d in (0,1))
            assert {k for k in a if a[k]!=b[k]}=={"deck"}
            assert sum(x!=y for x,y in zip(a["deck"],b["deck"],strict=True))==1
        for d in (0,1):
            a,b=(group[s,d]["spec"] for s in (0,1))
            assert {k for k in a if a[k]!=b[k]}=={"seed"}


def test_results_once_per_model_and_root():
    data=read(HERE/"ledger.json.gz")
    frozen=read(HERE/"manifest.json")
    assert frozen==manifest()
    assert n2b.stamp(frozen)==data["manifest_sha256"]
    cases={i["case"]["id"]:i["case"] for i in frozen["cases"]}
    assert set(data["root_audits"])==set(cases)
    assert Counter((r["id"],r["model"]) for r in data["rows"])=={
        (id_,m["id"]):1 for id_ in cases for m in frozen["models"]}
    assert all(r["evidence"]=="prediction_only" for r in data["rows"])
    assert all(r["loaded"]["sha256"] == data["versions"]["solver_sha256"] for r in data["lifecycle"])


def test_offline_shape_constraints_and_diagnostic_split():
    data=read(HERE/"representation.json")
    cases={i["case"]["id"]:i["case"] for i in manifest()["cases"]}
    fixtures=data["collision_and_invariance"]
    assert {"phase","hp_risk","draw_energy","nonlethal_target_threat","discard_collision","missing_preview"} <= set(fixtures)
    assert all(cases[v["id"]]["diagnostic_split"]=="diagnosis" for v in fixtures.values())
    a,b=fixtures["discard_collision"]["pair"]
    assert a["choice"]["id"]!=b["choice"]["id"] and a["features"]==b["features"]
    assert all(cases[r["id"]]["diagnostic_split"]=="diagnosis" for rs in data["divergence"].values() for r in rs)
    assert data["historical"]


def test_native_replays_stay_separate_from_prediction_evidence():
    audit=read(HERE/"native-audit.json")
    assert audit["manifest_sha256"] == n2b.stamp(manifest())
    assert len(audit["checks"]) == 8
    assert all(r.get("evidence")!="L3" for r in audit["checks"])
