"""Qualify two identical discard instances with A→B→A and independent native replay."""
import argparse
from dataclasses import asdict
from pathlib import Path

from interaction import Episode
from native_interaction import audit
from qualify_interaction import base


def run(game):
    initial = game.request("f1_audit")
    episode = Episode(game)
    rows = []
    for variant in (0, 1, 0):
        obs = episode.reset()
        candidates = [a for a in obs.actions if a.choice and a.choice.id == "STRIKE_SILENT"]
        first, second = candidates[:2]
        assert first.choice.upgrade == second.choice.upgrade
        for index, position in ((first.index, 1), (-1, 0)):
            invalid = game.request("i1_n2_step", index=index, position=position)["episode"]
            assert invalid["status"] == "invalid_action"
        selected = (first, second)[variant]
        after = episode.step(selected)
        assert after is not None and episode.state["actions"] == 1
        rows.append(dict(variant=variant, observation=asdict(obs), after=asdict(after),
                         selected=selected.native(), plan=episode.audit_actions[0], stamp=episode.audit_stamps[0]))
        episode.close()
        assert game.request("f1_audit") == initial
    assert rows[0] == rows[2] and rows[0]["plan"] != rows[1]["plan"]
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    versions = base.s3a.solver_binding(output, base.s3a.FIXED, base.ROOT / "logs/m1-e3f/release")
    item = next(c for c in base.cases() if c["case"].get("rule") == "shiv")
    data = dict(input=item, versions=versions, lifecycle=[], native=[])
    with base.worker(output, item, versions, data["lifecycle"]) as (game, _):
        data["variants"] = run(game)
    for row in data["variants"][:2]:
        episode = dict(trajectory=[dict(observation=row["observation"], action=row["selected"])],
                       terminal=dict(audit_actions=[row["plan"]], audit_stamps=[row["stamp"]],
                                     feedback=dict(combat_terminal=None)))
        with base.worker(output, item, versions, data["lifecycle"]) as (game, root):
            result = audit(game, root["public_root"], episode)
        choice, = result["choices"]
        assert choice["verified"] and choice["state_match"]
        assert choice["native_menu"] == choice["predicted_menu"]
        assert choice["native_index"] == choice["source_index"] == choice["selected"]
        data["native"].append(result)
    base.bank.atomic(output / "duplicate.json", data)


if __name__ == "__main__":
    main()
