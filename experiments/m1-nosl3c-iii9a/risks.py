"""Replay the eight original direct-risk probes under the pinned II-I.9A pair."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys

from replay import HERE, bind, certification

targets = certification.completion.targets
source = HERE.parent / "m1-nosl3c-iig-completion/evidence.json"


def main(output, solver):
    targets.configure()
    output.mkdir(parents=True)
    engine = bind(output, solver)
    originals = json.loads(source.read_bytes())["original_risks"]["results"]
    assert len(originals) == 8
    results = []
    for row in originals:
        with ExitStack() as stack:
            game = targets.open_worker(output, stack, engine)
            targets.CAPTURE(game, row["spec"])
            frames = game.request("i1_iif_direct", fixed_actions=row["route"])["boundaries"]
        results.append({**{key: row[key] for key in ("ledger", "step", "root")},
                        "before": row["boundaries"], "after": frames})
    (output / "risks.json").write_text(
        json.dumps(dict(engine=engine, results=results), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(*(Path(arg).resolve() for arg in sys.argv[1:]))
