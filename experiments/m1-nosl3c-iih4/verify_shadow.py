"""Compare independent native and predicted power application while combat continues."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "m1-nosl3c-iig-completion"))
from completion_engine import bind, iig, targets
from nosl_experience import save_json
from probe_prefix import native_step, target_indices


def verify(output, versions):
    spec = dict(schema=3, act=2, act_variant="HIVE", character="Defect", ascension=0,
                hp=75, max_hp=75, encounter="THIEVING_HOPPER_WEAK", seed="IIH4_SHADOW",
                relics=[], potions=[], deck=[dict(id="CONSUMING_SHADOW", upgrade=0)] +
                [dict(id="DEFEND_DEFECT", upgrade=0)] * 4)
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.request("i1_begin")
        initial = pred.request("i1_n2_reset", arm="A", cap=4, potions=False, rejected=[])["episode"]
        obs = targets.project(initial["observation"])
        slots = target_indices(pred, native)
        iig.audit.compare_menu(obs, b["public_root"], slots)
        action, = [a for a in obs["actions"] if a["card"] is not None and
                   obs["hand"][a["card"]]["id"] == "CONSUMING_SHADOW"]
        live = native_step(native, action, slots, [])
        step = pred.request("i1_n2_step", position=0, index=action["index"])["episode"]
        frame = native.request("i1_iib_native_stamp")
        raw = frame["state"][0]["exact_continuation_state"]
        assert live["decision"] == "combat_play" and not frame["terminal"] and step["status"] == "active"
        assert "CONSUMING_SHADOW_POWER=1/" in raw
        assert sha256(raw.encode()).hexdigest() == step["audit_stamp"]
        iig.audit.compare_menu(targets.project(step["observation"]), live, target_indices(pred, native))
        pred.request("i1_n2_close")
        return dict(spec=spec, terminal=False, exact_sha256=step["audit_stamp"],
                    powers=next(field for field in raw.split(";") if field.startswith("P=")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solver", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    targets.configure()
    versions = bind(output, args.solver.resolve())
    save_json(output / "nonlethal.json", dict(engine=versions, **verify(output, versions)))
