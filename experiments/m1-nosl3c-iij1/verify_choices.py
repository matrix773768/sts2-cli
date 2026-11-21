"""Verify generated choice ownership and replay the three related witnesses."""
from contextlib import ExitStack, closing
import gzip
from hashlib import sha256
import json
from pathlib import Path
import runpy
import sqlite3
import sys
from types import FunctionType

HERE = Path(__file__).resolve().parent
BASE = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii8/verify_root.py"))
bind = BASE["bind"]
targets = BASE["completion"].targets
from probe_prefix import native_step, target_indices
from qualify_native import native_action

compare_menu = BASE["completion"].iig.audit.compare_menu
save_json = BASE["save_json"]
LOGS = Path("logs")
RELATED = (("pair16", 0, "000004"), ("holdout", 0, "000020"), ("holdout", 1, "000005"))


def batch(folder, step, root):
    path = (LOGS / folder / "training.sqlite").resolve().as_uri()
    with closing(sqlite3.connect(path + "?mode=ro", uri=True)) as db:
        blob, = db.execute("SELECT rows FROM roots WHERE phase='train' AND step=? AND root=?",
                           (step, root)).fetchone()
    return json.loads(gzip.decompress(blob))


def quasar(output, versions, upgrade, select=True):
    spec = batch("iii9a-sample-8", 0, "000000")["spec"]
    spec = spec | {"deck": [card | {"upgrade": upgrade} if card["id"] == "QUASAR" else card
                            for card in spec["deck"]]}
    with ExitStack() as stack:
        pred, native = [targets.open_worker(output, stack, versions) for _ in range(2)]
        a, _ = targets.CAPTURE(pred, spec)
        b, _ = targets.CAPTURE(native, spec)
        assert a["native"] == b["native"]
        native.request("i1_begin")
        episode = pred.request("i1_n2_reset", arm="A", cap=8, potions=False, rejected=[])["episode"]
        live = b["public_root"]
        frames = []
        for index, card in enumerate(("MONOLOGUE", "VOID_FORM", "QUASAR")):
            obs = targets.project(episode["observation"])
            slots = target_indices(pred, native)
            compare_menu(obs, live, slots)
            action, = [a for a in obs["actions"] if a["card"] is not None
                       and obs["hand"][a["card"]]["id"] == card]
            live = native_step(native, action, slots, [])
            episode = pred.request("i1_n2_step", position=index, index=action["index"])["episode"]
            assert episode["status"] == "active", episode.get("detail")
            if card != "QUASAR":
                raw = native.request("i1_iib_native_stamp")["state"][0]["exact_continuation_state"]
                stamp = sha256(raw.encode()).hexdigest()
                assert stamp == episode["audit_stamp"]
                frames.append(dict(card=card, stamp=stamp))

        obs = targets.project(episode["observation"])
        compare_menu(obs, live, {})
        choice = obs["decision"]
        assert choice["effect"] == "GenerateToHand" and choice["pile"] == "None"
        assert len({c["id"] for c in choice["candidates"]}) == len(choice["candidates"]) == 3
        index, = [c["index"] for c in choice["candidates"] if c["id"] == "PANACHE"]
        assert choice["candidates"][index]["upgrade"] == upgrade
        invalid = pred.request("i1_n2_step", position=3, index=len(obs["actions"]))["episode"]
        assert invalid["status"] == "invalid_action"
        native_menu = [(c["id"], c["upgraded"]) for c in live["cards"]]
        if select:
            action, = [a for a in obs["actions"] if a["choice"] == index]
            episode = pred.request("i1_n2_step", position=3, index=action["index"])["episode"]
            obs = targets.project(episode["observation"])
            assert obs["decision"]["selected"] == [index]
            assert len(obs["actions"]) == 1
            confirm, = obs["actions"]
            live = native_step(native, confirm, {}, [index])
        else:
            confirm, = [a for a in obs["actions"] if a["kind"] == "confirm_selection"]
            # The native test adapter filters an out-of-range index to an empty selection.
            live = native_action(native, "select_cards", indices="999")
        episode = pred.request("i1_n2_step", position=4 if select else 3,
                               index=confirm["index"])["episode"]
        result = dict(spec=spec, choice=choice, native_menu=native_menu, frames=frames,
                      rejected=invalid, selected=index if select else None,
                      native_invalid_index_filtered=not select, status=episode["status"],
                      detail=episode.get("detail"))
        if episode["status"] == "active":
            raw = native.request("i1_iib_native_stamp")["state"][0]["exact_continuation_state"]
            stamp = sha256(raw.encode()).hexdigest()
            assert stamp == episode["audit_stamp"], targets.field_diff(
                pred.request("i1_iid_prediction_text")["text"], raw)
            after = targets.project(episode["observation"])
            compare_menu(after, live, target_indices(pred, native))
            generated = [c["upgrade"] for c in after["hand"] if c["id"] == "PANACHE"]
            assert generated == ([upgrade] if select else [])
            fields = dict(part.split("=", 1) for part in raw.split(";") if "=" in part)
            result.update(stamp=stamp, fields={key: fields[key] for key in ("H", "D", "R")},
                          legal_actions=after["actions"])
        pred.request("i1_n2_close")
    return result


def related(output, versions):
    probe = runpy.run_path(str(HERE.parent / "m1-nosl3c-iig-completion/probe_prefix.py"))["probe"]
    for suite, step, root in RELATED:
        folder = f"iii9b-{suite}"
        saved = batch(folder, step, root)
        audit = json.loads((LOGS / folder / "audit" / f"{step:06d}-{root}.json").read_bytes())
        transitions = saved["rows"][0]["transitions"]
        length = (audit.get("first_failure") or {}).get("position", len(transitions) - 1) + 1
        saved["rows"][0]["transitions"] = transitions[:length]
        result = probe(output, versions, saved, False, False)
        yield dict(suite=suite, step=step, root=root, prior=audit, observed=result)


if __name__ == "__main__":
    mode, dest, solver = sys.argv[1:]
    output = Path(dest).resolve()
    output.mkdir(parents=True)
    solver = Path(solver).resolve()
    targets.configure()
    versions = bind(output, solver)
    if mode == "quasar":
        cases = [quasar(output, versions, upgrade, select)
                 for upgrade, select in ((0, True), (1, True), (0, False))]
    elif mode == "related":
        cases = list(related(output, versions))
    elif mode == "instances":
        fixture = runpy.run_path(str(HERE.parent / "m1-nosl3c-iig-completion/verify/draw_instances.py"))
        verify = fixture["verify"]
        with fixture["torch"].no_grad():
            FunctionType(verify.__code__, verify.__globals__ | {"bind": bind})(output, solver)
        raise SystemExit(0)
    else:
        raise ValueError(mode)
    save_json(output / (mode + ".json"), dict(engine=versions, cases=cases))
