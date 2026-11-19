"""Exercise a current cost change and reject invalid actions on an open development fixture."""
import argparse
from dataclasses import asdict
from pathlib import Path

from environment import Episode
from native_check import differences
from qualify import ROOT, bank, cases, s3a, worker


def fixture():
    first = next(cases())["case"]["spec"]
    spec = first | dict(seed="N2ACOST00001", relics=[], potions=[None, None, None],
                        deck=[dict(id=card, upgrade=0)
                              for card in ["STRIKE_IRONCLAD"] * 4 + ["STOMP"] * 4])
    return dict(case=dict(id="n2a-cost-01", split="development", spec=spec),
                synthetic=True, natural_reachability="unknown")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    versions = s3a.solver_binding(output, s3a.FIXED, ROOT / "logs/m1-e3f/release")
    item = fixture()
    data = dict(input=item, versions=versions, lifecycle=[], rejections=[])
    with worker(output, item, versions, data["lifecycle"]) as (game, root):
        env = Episode(game)
        before = env.reset()
        data["wire"] = env.state["observation"]
        for position, index, expected in ((1, 0, "Stale action position"),
                                          (0, -1, "Action index outside current menu")):
            try:
                game.request("i1_n2_step", index=index, position=position)
            except bank.f1.i2.StopRun as error:
                if expected not in str(error):
                    raise
                data["rejections"].append(str(error))
            else:
                raise ValueError("Invalid action accepted")
        action = next(a for a in before.actions if a.card is not None
                      and before.hand[a.card].id == "STRIKE_IRONCLAD")
        after = env.step(action)
        assert env.state["transitions"] == 1
        data.update(before=asdict(before), after=asdict(after) if after else env.result(),
                    action=action.native())
        env.close()
        assert env.reset() == before
        env.close()
    with worker(output, item, versions, data["lifecycle"]) as (game, root):
        initial = root["public_root"]
        subsequent = game.execute_action(data["action"])
        data["before_diff"] = differences(data["before"], initial)
        if subsequent["decision"] == "combat_play" and after is not None:
            data["after_diff"] = differences(data["after"], subsequent)
        data["native"] = [dict(decision=state["decision"],
                               hand=[(c["id"], c["cost"]) for c in state.get("hand", [])])
                          for state in (initial, subsequent)]
    bank.atomic(output / "mechanics.json", data)


if __name__ == "__main__":
    main()
