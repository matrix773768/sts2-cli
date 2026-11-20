"""Extend the isolated IIF direct probe with a private interaction trace."""
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
BASE = runpy.run_path(str(HERE.parent / "m1-nosl3c-iif/build_host.py"))
HOST = "m1-nosl3c-iig-build"


def stage(src):
    BASE["stage"](src)
    edit = BASE["BASE"]["BASE"]["BASE"]["BINDING"].edit
    edit(src/"InteractiveEpisode.cs", "            audit_action = InteractiveProperty<PlanAction?>",
         '''            interaction_trace = _interactive!.GetType()
                .GetProperty("InteractionTrace", BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(_interactive),
            audit_action = InteractiveProperty<PlanAction?>''')


if __name__ == "__main__":
    i1 = BASE["BASE"]["BASE"]["BASE"]["BINDING"].b1b.b1a.i1
    i1.build(i1.ROOT/"logs"/HOST,stage)
