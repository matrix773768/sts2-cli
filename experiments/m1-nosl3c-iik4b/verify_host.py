"""Check the isolated host with only the Rolling Boulder witness and a reduced control."""
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
import runpy
import sys
from time import perf_counter
from types import FunctionType

HERE = Path(__file__).resolve().parent
tools = runpy.run_path(str(HERE.parent / "m1-nosl3c-iij1/verify_choices.py"))
from probe_prefix import native_step, probe

LEDGER = "iij5b-serial-pair16"
TARGETS = tools["targets"]


def binder(host):
    identity = json.loads((host / "build.json").read_bytes())
    assert identity["version"] == "II-K.4B"
    for name, artifact in identity["artifacts"].items():
        file = host / "Headless/bin/Debug/net9.0" / name
        assert sha256(file.read_bytes()).hexdigest() == artifact["sha256"]
    original = TARGETS.bind
    raw_bind = FunctionType(original.__code__, original.__globals__ | {"HOST": host.name})

    def bind(output, solver):
        versions = raw_bind(output, solver)
        assert versions["solver"] == "0.51.5-iik.3b"
        assert versions["headless_sha256"] == identity["artifacts"]["OfflineSearchHarness.dll"]["sha256"]
        return versions | {"godot_sha256": identity["artifacts"]["GodotSharp.dll"]["sha256"]}

    return bind


def fixture(output, versions, spec):
    # Schema 1 accepts the colorless Rolling Boulder in a short Regent deck.
    spec = spec | dict(schema=1, act_variant=None, deck=[
        dict(id="ROLLING_BOULDER", upgrade=0),
        *[dict(id="DEFEND_REGENT", upgrade=0)] * 4,
    ])
    with ExitStack() as stack:
        native = TARGETS.open_worker(output, stack, versions)
        setup, _ = TARGETS.CAPTURE(native, spec)
        native.teacher_choices, native.teacher_frames = [], []
        native.request("i1_begin")
        live = setup["public_root"]
        card, = [card for card in live["hand"] if card["id"] == "CARD.ROLLING_BOULDER"]
        assert card["can_play"]
        played = native_step(native, dict(kind="play_card", card=card["index"], target_side=None), {}, [])
        after = native_step(native, dict(kind="end_turn"), {}, [])
        assert after["decision"] == "combat_play"
        before_hp = [enemy["hp"] for enemy in played["enemies"]]
        after_hp = [enemy["hp"] for enemy in after["enemies"]]
        assert len(before_hp) == len(after_hp) and all(a < b for a, b in zip(after_hp, before_hp))
        return dict(before_hp=before_hp, after_hp=after_hp, decision=after["decision"])


if __name__ == "__main__":
    mode = sys.argv[1]
    output, solver, host = (Path(arg).resolve() for arg in sys.argv[2:])
    bind = binder(host)
    start = perf_counter()
    if mode == "resample":
        sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iij2"))
        from resample import main
        main = FunctionType(main.__code__, main.__globals__ | {"TOOLS": main.__globals__["TOOLS"] | {"bind": bind}},
                            argdefs=main.__defaults__)
        main(output, solver, suite="pair16", cases=((0, "000001"),), ledger_name=LEDGER)
    else:
        output.mkdir(parents=True)
        TARGETS.configure()
        versions = bind(output, solver)
        batch = tools["batch"](LEDGER, 0, "000001")
        assert len(batch["rows"][0]["transitions"]) == 37
        result = fixture(output, versions, batch["spec"]) if mode == "fixture" else (
            probe(output, versions, batch, False, False))
        tools["save_json"](output / f"{mode}.json", {"result": result, "engine": versions})
        print({k: v for k, v in result.items() if k not in ("native", "public", "steps")})
    print("SECONDS", perf_counter() - start)
