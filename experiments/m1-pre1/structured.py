"""Structured synthetic Ironclad curriculum using the PRE0B producer."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import random
import runpy
import sys


HERE = Path(__file__).resolve().parent
PACKAGES = (
    ("INFLAME", "TWIN_STRIKE", "SWORD_BOOMERANG", "POMMEL_STRIKE", "SHRUG_IT_OFF"),
    ("OFFERING", "POMMEL_STRIKE", "BATTLE_TRANCE", "BLOODLETTING", "UPPERCUT"),
    ("BARRICADE", "BODY_SLAM", "FLAME_BARRIER", "SHRUG_IT_OFF", "IMPERVIOUS"),
    ("RUPTURE", "HEMOKINESIS", "OFFERING", "BLOOD_WALL", "TWIN_STRIKE"),
)


def run(args, manifest_path):
    previous = HERE.parent / "m1-pre0b"
    sys.path.insert(0, str(previous))
    runtime = runpy.run_path(str(previous/"run.py"))
    base_root, digest = runtime["root"], runtime["digest"]
    seed_cfg = json.loads((HERE/"structured-roots.json").read_bytes())
    config = seed_cfg | {"root_builder_sha256": sha256(Path(__file__).read_bytes()).hexdigest()}
    if manifest_path.exists() and json.loads(manifest_path.read_bytes()) != config:
        raise ValueError("Structured source identity changed")
    manifest_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    args.config = manifest_path

    def structured(catalog, config, ordinal):
        spec, _, _, room = base_root(catalog, config, ordinal)
        role, = [r for r in catalog["characters"] if r["name"] == "Ironclad"]
        native = {card["id"]: card for card in role["cards"] if card["id"] not in config["exclude"]}
        rng = random.Random(digest([config["seed"], ordinal, "package"]))
        package = PACKAGES[ordinal % len(PACKAGES)]
        if not set(package).issubset(native):
            raise ValueError("A structured card is absent from the frozen native pool")
        starter = list(role["starter"])
        # Nested refinements retain their family even with different flexible slots.
        for _ in range(ordinal % 3):
            index = next((i for i,c in enumerate(starter) if c=="STRIKE_IRONCLAD"), None)
            if index is not None:
                starter.pop(index)
        cards = starter + list(package) + rng.choices(package, k=rng.randrange(3))
        rng.shuffle(cards)
        spec["deck"] = [dict(id=card, upgrade=int(native[card]["upgradable"] and rng.random() < .25))
                        for card in cards]
        # This curriculum is training-only. Starter-related families deliberately
        # share a split, including refinements that overlap across packages.
        return spec, "train", digest([config["version"], package]), room

    runtime["produce"].__globals__["root"] = structured
    runtime["produce"](args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--count", type=int, default=3600)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(exist_ok=True)
    args.fast, args.buffered_logs, args.update = True, True, 84
    args.batch, args.recycle, args.batch_delay = args.workers, 96, 0.
    args.cap, args.worker_mib, args.disk_mib, args.seconds = 256, 512, 2048, 7200
    run(args, args.output/"source-config.json")
