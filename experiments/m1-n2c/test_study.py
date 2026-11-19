from collections import Counter

from repeat_study import BASE, BASELINE, HERE, PROTOCOL, make_report, n2b, read, zero_models


def test_new_report_seed_and_variant_contract():
    old = read(BASE/"manifest.json")["cases"]
    sources = {i["case"]["id"]:i["case"] for i in old}
    new = list(make_report(old))
    assert len(new) == 48
    seeds = {i["case"]["spec"]["seed"] for i in new}
    assert len(seeds) == 48 and seeds.isdisjoint(i["case"]["spec"]["seed"] for i in old)
    assert {i["case"]["spec"]["encounter"] for i in new} == set(PROTOCOL["report_encounters"])
    assert Counter(i["case"]["arm"] for i in new) == {"new_seed":24, "deck_variant":24}
    for item in new:
        c = item["case"]
        previous = sources[c["source_id"]]["spec"]
        different = {k for k in previous if previous[k] != c["spec"][k]}
        assert different == ({"seed"} if c["arm"] == "new_seed" else {"seed","deck"})
        assert c["spec_sha256"] == n2b.stamp(c["spec"])
        assert item["synthetic"] and item["natural_reachability"] == "unknown"


def test_untrained_controls_and_inherited_schedule():
    models = zero_models()
    assert models == zero_models()
    assert models[0]["weights"] == n2b.CONFIG["initial_mean"]
    assert len({tuple(m["weights"]) for m in models}) == 3
    plan = read(BASE/"manifest.json")
    original = read(BASELINE/"ledger.json.gz")["schedule"]
    assert original == [[x["case"]["id"] for x in b] for b in n2b.schedule(plan["cases"])]


def test_budget_splits_lock_and_first_generation_pairs():
    data = read(HERE/"ledger.json.gz")
    models = read(HERE/"models.json")
    digest = models.pop("sha256")
    manifest = read(HERE/"manifest.json")
    plan = read(BASE/"manifest.json")["cases"]
    assert manifest["cases"] == list(make_report(plan))
    assert digest == data["locked_sha256"] == manifest["locked_sha256"] == n2b.stamp(models)
    assert data["new_manifest_sha256"] == n2b.stamp(manifest)
    assert data["inherited"] == n2b.CONFIG
    assert all(r["evidence"] == "prediction_only" for phase in data["passes"] for r in phase["rows"])
    assert all(root["loaded"]["sha256"] == data["versions"]["solver_sha256"]
               for phase in data["passes"] for root in phase["lifecycle"])
    counts = Counter()
    for phase, schedule in zip(data["passes"][:4],data["schedule"],strict=True):
        for m in phase["models"]:
            rows = [r for r in phase["rows"] if r["model"] == m["id"]]
            assert {r["id"] for r in rows} == set(schedule) and len(rows) == 12
            counts[m["repeat"],m["method"]] += len(rows)
    assert len(counts) == 4 and set(counts.values()) == {576} and sum(counts.values()) == 2304
    selection, train_zero, old_report, new_report = data["passes"][-4:]
    assert [len(p["rows"]) for p in (selection,train_zero,old_report,new_report)] == [456,144,168,528]
    assert set(new_report["scores"]) == {m["id"] for m in models["models"]}
    first = data["passes"][0]
    for model in first["models"]:
        if model["method"] == "cem":
            peer = model["id"].replace("-cem-","-random-")
            assert model["weights"] == next(m["weights"] for m in first["models"] if m["id"] == peer)
            for root in data["schedule"][0]:
                a,b = (next(r["terminal"] for r in first["rows"] if (r["id"],r["model"])==(root,name))
                       for name in (model["id"],peer))
                assert {k:v for k,v in a.items() if not k.endswith("_ms")} == {
                    k:v for k,v in b.items() if not k.endswith("_ms")}


def test_report_native_checks_are_independent():
    audit = read(HERE/"native-audit.json")
    assert len(audit["checks"]) == 8
    assert audit["locked_sha256"] == read(HERE/"models.json")["sha256"]
    assert all(r.get("evidence") != "L3" for r in audit["checks"])
