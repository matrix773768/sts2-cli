"""Stage the F3B host beside the existing isolated experiments."""
import importlib.util
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-f3a"))
spec = importlib.util.spec_from_file_location("f3a_build", HERE.parent / "m1-f3a/build.py")
f3a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f3a)


def stage(src):
    f3a.stage(src)
    edit = f3a.f2.replace
    for file in HERE.glob("*.cs"):
        shutil.copyfile(file, src / file.name)
    for declaration in ("record Enemy", "record Move", "record Observation", "Move? Decide("):
        frozen = src / "FrozenQ1.cs"
        marker = "private sealed " if declaration.startswith("record") else "private static "
        replacement = "internal sealed " if declaration.startswith("record") else "internal static "
        edit(frozen, marker + declaration, replacement + declaration)
    q5 = (HERE.parent / "m1-q5/TargetedSearch.cs").read_text(encoding="utf-8")
    observe = q5[q5.index("    private PublicState ObservePrediction"):
                 q5.index("    private PlanAction ToPlan")]
    observe = observe.replace("FastCombat.", "RealCombat.").replace("or TargetType.AllEnemies or TargetType.RandomEnemy",
        "or TargetType.AllEnemies or TargetType.RandomEnemy or TargetType.TargetedNoCreature")
    header = q5[:q5.index("namespace ")]
    (src / "Projection.cs").write_text(header + """
namespace OfflineSearchHarness;
internal sealed partial class FirstWin
{
    private sealed record PublicState(RealCombat.Observation Menu, int Hp, int Energy, int? Sandpit,
        string[] Hand, string[] Powers, string[] EnemyPowers);
""" + observe + "}\n", encoding="utf-8")
    probe = src / "IntegrationProbe.cs"
    edit(probe, '        var root = CombatRootSnapshot.Capture(live);',
        '''        if (command == "i1_f3b")
            return RunFirstWin(live, cmd);
        var root = CombatRootSnapshot.Capture(live);''')
    edit(probe, '            case "i1_capture": break;', '            case "i1_f3b":\n            case "i1_capture": break;')


if __name__ == "__main__":
    f3a.f2.f1.i1.build(f3a.f2.f1.i1.ROOT / "logs/m1-f3b-build", stage)
