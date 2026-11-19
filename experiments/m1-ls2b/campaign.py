"""Freeze and resume paired LS2B campaigns on the LS2A transactional scheduler."""
import argparse
from collections import Counter
from contextlib import closing
from pathlib import Path
from random import Random

from spec import HERE, VERSION, context, digest
import execute
import learning
import pipeline
import store
from engine import bank, catalog as native_catalog, ls1
from ls1_design import file_hash, read
from space import check_splits, key, synthetic

ARMS = ("baseline", "generated", "repair", "learned")


def binding(directory):
    versions = ls1.setup(directory, host="m1-ls2b-build")
    files = [HERE / n for n in ("build.py", "Strategy.cs", "spec.py", "learning.py", "execute.py", "campaign.py")]
    files += [HERE.parent / "m1-ls2a" / n for n in ("build.py", "space.py", "engine.py", "pipeline.py", "store.py")]
    return versions | dict(strategy=VERSION, generator=execute.GENERATOR,
                           implementation=digest([file_hash(p, True) for p in files]))


def immutable(path, value):
    if path.exists():
        if read(path) != value:
            raise ValueError(f"Immutable artifact differs: {path}")
    else:
        bank.atomic(path, value)


def cases_for(catalog, config, name):
    sampling = read(HERE.parent / "m1-ls2a/config.json") | config["sampling"]
    population = synthetic(catalog, sampling, config["pool"], config["namespace"])
    grouped = {role["name"]: [] for role in catalog["characters"]}
    partition = "test" if name == "report" else "train"
    for case in population:
        if case["split"] == partition:
            grouped[case["spec"]["character"]].append(case)
    selected = []
    for i in range(config["counts"][name]):
        role = sorted(grouped)[i % len(grouped)]
        selected.append(grouped[role][i//len(grouped)])
    return selected


def plan(directory, cfg, name, catalog, versions, prior, model):
    if name == "report" and (not model or model["binding"] != digest(versions)):
        raise ValueError("Report requires a matching frozen development model")
    cases = cases_for(catalog, cfg, name)
    check_splits([*prior, *cases])
    if {c["id"] for c in cases} & {c["id"] for c in prior}:
        raise ValueError("Pilot/development/report roots overlap")
    jobs = []
    for case in cases:
        if name == "development":
            profiles = [["probe", i, cfg["probe_cap"]] for i in range(cfg["probes"])]
        else:
            arms = ARMS if name == "report" else ARMS[:3]
            profiles = [[arm, None, cap] for arm in arms for cap in cfg["budgets"]]
            if name == "report":
                profiles.extend(["legacy_probe", policy, 48] for policy in ls1.STRATEGIES)
        Random(key(["paired-arm-order", case["id"]])).shuffle(profiles)
        case["schedule"] = dict(profiles=profiles)
        reserved = sum(p[2] for p in profiles)
        cache = digest([versions, digest(catalog), case["spec"], profiles, name, model, cfg])
        jobs.append(dict(id=case["id"], case=case, cache=cache, reserved=reserved))
    if sum(j["reserved"] for j in jobs) > cfg["limits"]["transitions"]:
        raise ValueError("Campaign exceeds phase allocation")
    return dict(schema="ls2b.manifest.v1", name=name, config=cfg | dict(model=model),
                versions=versions, catalog_sha256=digest(catalog), jobs=jobs)


def examples(db, name):
    manifest = store.unpack(db.execute("SELECT manifest FROM plans WHERE plan=?", (name,)).fetchone()[0])
    cases = {j["id"]: j["case"] for j in manifest["jobs"]}
    for id_, item in store.results(db, name):
        if item["outcome"] != "complete":
            continue
        for cell in item["cells"]:
            a = cell["outcome"]["attempts"]
            yield dict(schema="ls2b.experience.v1", split=name, root=id_, source=cases[id_]["source"],
                       public_context=item["public"], context=context(item["public"]), gaps=item["gaps"],
                       evidence_level=item["evidence"], profile=cell["profile"], attempts=a)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("pilot", "development", "fit", "report"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--max-new", type=int)
    args = parser.parse_args()
    out = args.directory.resolve()
    out.mkdir(parents=True, exist_ok=True)
    name = args.command
    cfg = read(args.config)
    with bank.writer(out), closing(store.open_store(out/"search.sqlite")) as db:
        versions = binding(out)
        if name == "fit":
            if db.execute("SELECT COUNT(*) FROM tasks WHERE plan='development' AND state!='done'").fetchone()[0]:
                raise ValueError("Development phase has unsettled tasks")
            frozen = store.unpack(db.execute("SELECT manifest FROM plans WHERE plan='development'").fetchone()[0])
            if frozen["versions"] != versions:
                raise ValueError("Development implementation differs")
            fitted = learning.fit(examples(db, "development"), digest(versions))
            immutable(out/"model.json", fitted)
            print(fitted["samples"], fitted["positives"], digest(fitted))
            return
        catalog = native_catalog(out, versions)
        immutable(out/"catalog.json", catalog)
        prior = [j["case"] for (blob,) in db.execute("SELECT manifest FROM plans WHERE plan!=?", (name,))
                 for j in store.unpack(blob)["jobs"]]
        model = read(out/"model.json") if name == "report" else None
        manifest = plan(out, cfg, name, catalog, versions, prior, model)
        store.register(db, manifest, manifest["jobs"])
        pipeline.run(db, out, manifest, catalog, cfg["limits"]["workers"], args.max_new, execute=execute.execute)


if __name__ == "__main__":
    main()
