"""Check current dynamic STOMP cost through the expanded observation DTO."""
import argparse
import json
from dataclasses import asdict
from pathlib import Path

from interaction import Episode
from mechanics import fixture
from native_interaction import compare
from qualify_interaction import base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    versions = base.s3a.solver_binding(output, base.s3a.FIXED, base.ROOT / "logs/m1-e3f/release")
    item = fixture()
    data = dict(input=item, lifecycle=[], versions=versions)
    with base.worker(output, item, versions, data["lifecycle"]) as (game, _):
        episode = Episode(game)
        obs = episode.reset()
        action = next(a for a in obs.actions if a.card is not None and obs.hand[a.card].id == "STRIKE_IRONCLAD")
        after = episode.step(action)
        data.update(before=asdict(obs), after=asdict(after))
        episode.close()
    with base.worker(output, item, versions, data["lifecycle"]) as (game, root):
        state = root["public_root"]
        # Canonicalize tuples to match the serialized benchmark DTO.
        before, after = (json.loads(json.dumps(data[key])) for key in ("before", "after"))
        data["diffs"] = compare(before, state) + compare(after, game.execute_action(action.native()))
    base.bank.atomic(output / "mechanics.json", data)


if __name__ == "__main__":
    main()
