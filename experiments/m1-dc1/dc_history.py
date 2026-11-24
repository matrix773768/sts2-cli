"""Audit the released historical assets and materialize reusable exact outcome labels."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import gzip
import io
import json
from pathlib import Path

from dc_common import PRIOR, ROOT, checksum, read, write_json
from dc_metrics import describe
from dc_roots import static
from dc_utility import labels
from loop_battle import read_ledger
from sv_data import config as sv3config, db_for, decoded


def history():
    for key, relative in sv3config()["sources"].items():
        path = ROOT / relative
        with closing(db_for(path)) as db:
            metadata = dict(split_counts=dict((f"{split}:{complete}", n) for split, complete, n in
                db.execute("SELECT split,complete,count(*) FROM trajectories GROUP BY split,complete")))
            manifest = json.loads(db.execute("SELECT json FROM manifest").fetchone()[0])
            metadata["producer"] = {k: v for k,v in manifest.items() if k not in ("allowed_cards", "native_identity")}
            # SQLite excludes the sealed partition before payload decompression.
            cursor = db.execute("""SELECT t.sha,t.payload FROM trajectories t
                       WHERE t.split IN ('train', 'validation') ORDER BY t.ordinal""")
            yield key, path, metadata, (decoded(sha, blob) for sha,blob in cursor)
    path = ROOT / "logs/m1-sv3a-new/experience/random-71393001"
    from sv_eval import load_rows
    yield "sv3a-experience", path/"results.sqlite", {}, (item["row"] for item in load_rows(path))
    for arm in ("D1","D2","S1","S2"):
        path = PRIOR/"experience"/arm
        yield f"sv4a-{arm}", path/"results.sqlite", {}, (r["row"] for r in read_ledger(path, full=False))


class Errors:
    def __init__(self):
        self.counts = Counter()
        self.errors = defaultdict(list)
        self.thresholds = Counter()

    def add(self, value):
        self.counts["complete"] += 1
        self.counts["death"] += value["death"]
        self.counts["negative_net"] += value["net_loss"] < 0
        self.counts["max_hp_change"] += value["max_hp_delta"] != 0
        self.counts["positive_hp_credit"] += (value["hp_credit"] or 0) > 0
        self.counts["missing_cumulative"] += value["cumulative_loss"] is None
        for field, name in (("net_loss","net_bin"),("cumulative_loss","cumulative_bin")):
            if value[field] is not None and value[name] is not None:
                self.errors[name].append(abs(value[field] - value[name]))
            elif value[field] is not None:
                self.counts[name+"-overflow"] += 1
        if value["death"]:
            return
        actual = value["net_loss"]
        fraction = (value["old_class"]-1)/31
        hp = fraction * value["end_max_hp"]
        reconstructed = value["start_hp"] - hp
        errors = {
            "hp_fraction_grid": abs(reconstructed-actual),
            "hp_grid_using_start_max": abs(value["start_hp"]-fraction*value["start_max_hp"]-actual),
            "U0": .25*abs(hp-value["end_hp"])/value["end_max_hp"],
            "U1": .25*abs(reconstructed-actual)/80,
        }
        if value["cumulative_loss"] is not None:
            from dc_utility import loss_curve
            errors["U2_using_net_as_cumulative"] = .25/80*abs(loss_curve(max(0,reconstructed)) -
                                                            loss_curve(value["cumulative_loss"]))
        for key, val in errors.items():
            self.errors[key].append(val)
        bands = lambda n: "negative" if n < 0 else "zero" if n==0 else "1-5" if n<=5 else "6-10" if n<=10 else ">10"
        self.thresholds[f"{bands(actual)} -> {bands(round(reconstructed))}"] += 1

    def summarize(self):
        from dc_metrics import average, quantiles
        return dict(counts=self.counts, confusion=self.thresholds,
            errors={k:dict(n=len(v), mean=average(v), maximum=max(v), quantiles=quantiles(v))
                    for k,v in self.errors.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output
    catalog = read(output/"roots/catalog.json")["characters"][0]["cards"]
    cards = {c["id"]:c for c in catalog}
    distribution = {}
    error = defaultdict(Errors)
    final = output/"historical-labels.jsonl.gz"
    partial = final.with_suffix(".partial")
    with (partial.open("wb") as raw,
          gzip.GzipFile(fileobj=raw, filename="", mode="wb", compresslevel=3, mtime=0) as compressed,
          io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as stream):
        for name, path, metadata, data in history():
            counters = defaultdict(Counter)
            summaries = defaultdict(list)
            for row in data:
                spec = row["root"]
                hp = spec["max_hp"]
                group = f"{spec['hp']}/{hp}"
                attributes = static(spec["deck"], cards)
                for key in ("size","unique","strikes","defends","bash","basics","upgraded"):
                    counters[key][str(attributes[key])] += 1
                for key in ("card_types","rarity","mechanics"):
                    counters[key].update(attributes[key])
                counters["interactions"].update(attributes["interactions"])
                counters["room_source"][f"{spec['act']}:{row['room']}"] += 1
                counters["resource"][f"relics={len(spec['relics'])},potions={len(spec['potions'])}"] += 1
                counters["policy_status"][f"{row['behavior']['model_sha256']}:{row['status']}"] += 1
                decisions = row.pop("steps", [])
                obs = next((step["observation"] for step in decisions if "observation" in step), None)
                if obs:
                    counters["opening_energy"][str(obs["energy"])] += 1
                summaries[group].append(row)
                if not row["complete"]:
                    continue
                value = labels(row)
                error[str(hp)].add(value)
                error[f"{hp}:max_change={value['max_hp_delta']!=0}"].add(value)
                first = decisions[0]["action"]["index"] if decisions else None
                # Only accumulated root loss is exact. No running damage
                # counter is available on these historical decision wires.
                stream.write(json.dumps(dict(source=name, id=row["id"], family=row["family"], split=row["split"],
                    first_action=first, **value), separators=(",",":"), ensure_ascii=False)+"\n")
            distribution[name] = dict(path=path.relative_to(ROOT).as_posix(), input_sha256=checksum(path),
                metadata=metadata, composition=counters, by_hp={k:describe(v) for k,v in summaries.items()},
                overall=describe(row for group in summaries.values() for row in group))
            print(name, distribution[name]["overall"]["attempts"], flush=True)
    partial.replace(final)
    ii = ROOT/"experiments/m1-nosl3c-iie"
    historical = dict(protocol=read(ROOT/"logs/nosl3c-iii-a2-01/protocol.json")["config"]["objective"],
        config=read(ii/"integration.json")["objective"],
        objective_sha256=checksum(ii/"objective.py"),
        evidence_sha256=checksum(ii/"evidence.json"))
    write_json(output/"history.json", dict(sources=distribution, buckets={k:v.summarize() for k,v in error.items()},
                   historical_utility=historical, labels=dict(path=final.name,sha256=checksum(final))))


if __name__ == "__main__":
    main()
