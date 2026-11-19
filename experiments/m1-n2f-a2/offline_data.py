"""Audit training-only archives and freeze the five background folds."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "m1-n2f-a"
sys.path.insert(0, str(BASE))
from study_design import FAMILIES, DOMAIN, ENCOUNTERS, digest, load_catalog, deck_from_root, save, read

LABELS = {"predicted_win": 0, "death": 1, "truncated": 2}
FIELDS = {"character", "hp", "max_hp", "encounter", "ascension", "act", "relics", "potions", "deck"}


def require(test, message):
    if not test:
        raise ValueError(message)


def archive(name, hashes):
    source = (BASE / name).read_bytes()
    require(hashlib.sha256(source).hexdigest() == hashes[name], f"Archive changed: {name}")
    return json.loads(gzip.decompress(source))


def load():
    hashes = read(BASE / "artifact-hashes.json")
    dataset = archive("data.json.gz", hashes)
    ledger = archive("ledger.json.gz", hashes)
    require(set(dataset) == {"train"} and not ledger["native"], "Expected training-only archive")
    rows = dataset["train"]
    ids = {r["audit"]["id"] for r in rows}
    traces = {r["id"]: r for r in ledger["rows"]}
    require(len(rows) == len(ids) == len(traces) == len(ledger["rows"]) == 320
            and ids == traces.keys(), "Root IDs do not correspond")
    require(len(ledger["budget"]) == 320 and {r["id"] for r in ledger["budget"]} == ids
            and all(r["phase"] == "train" for r in ledger["budget"]), "Unexpected budget")
    prior = read(BASE / "protocol.json")
    require(prior["action_cap"] == 96 and ledger["manifest_sha256"] == prior["manifest_sha256"]
            and all(ledger["versions"][k] == v for k, v in prior["versions"].items()), "Prior lock differs")
    require(Counter(r["status"] for r in rows) == dict(predicted_win=143, death=116, truncated=61),
            "Unexpected outcome counts")
    catalog = load_catalog()
    require(catalog.content_sha256 == prior["catalog_sha256"], "Catalog differs")
    groups = defaultdict(list)
    for row in rows:
        audit, inputs = row["audit"], row["input"]
        key = audit["id"]
        status = row["status"]
        trace = traces[key]
        feedback = trace["terminal"]["feedback"]
        family = audit["family"]
        template = audit["template"]
        pair = audit["pair"]
        a, b = audit["slot_a"], audit["slot_b"]
        require(set(inputs) == FIELDS and all(set(c) == {"id", "upgrade"} for c in inputs["deck"]),
                f"Unexpected public fields: {key}")
        require(audit["cohort"] == trace["phase"] == "train" and audit["split"] == "development"
                and audit["synthetic"] and template in {f"{family}-train-{n}" for n in range(5)}
                and inputs["character"] == FAMILIES[family][0] and inputs["encounter"] in ENCOUNTERS,
                f"Unexpected development root: {key}")
        require(pair in {digest([DOMAIN, template, inputs["encounter"], n]) for n in range(4)}
                and key == digest([pair, a, b])[:16]
                and digest(dict(inputs, schema=2, seed=pair[:12].upper(), act_variant="HIVE"))
                == audit["spec_sha256"], f"Original specification differs: {key}")
        require(trace["lifecycle"]["id"] == key and bool(trace["lifecycle"]["root_sha256"])
                and trace["evidence"] == row["evidence"] == "prediction_only"
                and trace["terminal"]["status"] == feedback["status"] == status
                and len(trace["trajectory"]) <= 96, f"Outcome mismatch: {key}")
        if status == "truncated":
            require(row["label"] is None and row["winning_hp"] is None and len(trace["trajectory"]) == 96
                    and feedback["combat_terminal"] is None
                    and feedback["missing_reason"] == row["missing_reason"] == "action_cap", f"Cap mismatch: {key}")
        else:
            hp = feedback["combat_terminal"]["hp"]
            require(row["label"] == int(status == "predicted_win") and row["missing_reason"] is None
                    and row["winning_hp"] == (hp if status == "predicted_win" else None), f"Label differs: {key}")
        deck = deck_from_root(inputs["character"], inputs["deck"])
        identity = catalog.encode_deck(deck, "identity")
        mechanics = catalog.encode_deck(deck)
        require(identity["content_sha256"] == mechanics["content_sha256"] == audit["deck_sha256"]
                and catalog.encode_deck(catalog.decode_identity_deck(identity)) == mechanics
                and all(e["card"]["qualification"] == "static_described" for e in mechanics["cards"]),
                f"Deck encoding differs: {key}")
        groups[template].append(row)
    require(len(groups) == 10 and all(len(g) == 32 for g in groups.values()), "Wrong background counts")
    for group in groups.values():
        pairs = defaultdict(list)
        for r in group:
            a = r["audit"]
            pairs[a["pair"]].append((a["slot_a"], a["slot_b"]))
        require(len(pairs) == 8 and all(sorted(v) == [(0, 0), (0, 1), (1, 0), (1, 1)]
                                        for v in pairs.values()), "Incomplete paired blocks")
    return sorted(rows, key=lambda r: r["audit"]["id"])


def fold_plan(rows):
    return [{"index": i, "held_groups": [f"{f}-train-{i}" for f in FAMILIES],
             "held_ids": [r["audit"]["id"] for r in rows
                          if r["audit"]["template"] in {f"{f}-train-{i}" for f in FAMILIES}]}
            for i in range(5)]


def freeze():
    rows = load()
    save(HERE / "protocol.json", dict(scope="exploratory / offline / reused-development-data",
         source_hashes={name: read(BASE / "artifact-hashes.json")[name]
                        for name in ("data.json.gz", "ledger.json.gz")},
         records_sha256=digest(rows), new_rollouts=0, action_cap=96, classes=["win", "death", "unfinished"],
         seed=[17, 43, 101], epochs=90, hidden=12, card_dim=128, learning_rate=.015, l2=.002,
         optimizer="full-batch Adam (0.9, 0.999, 1e-8)", fit_wall_limit_seconds=120,
         prior={"strata": ["family", "encounter"], "laplace_alpha": 1},
         brier="mean over roots of sum over classes of squared error",
         bootstrap={"seed": 771, "replicates": 2000, "unit": "background within family"},
         folds=fold_plan(rows)))


if __name__ == "__main__":
    freeze()
