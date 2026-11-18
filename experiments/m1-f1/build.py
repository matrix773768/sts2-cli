"""Build the isolated I1 host with the frozen Q1/Q3 policy."""
import sys
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-i1"))
import build as i1


def replace(path, old, new):
    source = path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise ValueError(f"Unexpected source at {path.name}: {old}")
    path.write_text(source.replace(old, new), encoding="utf-8")


def stage(src):
    fast = (HERE.parent / "m1-q1/FastCombat.cs").read_text(encoding="utf-8")
    imports = fast[:fast.index("namespace ")]
    observe_and_decide = fast[fast.index("    private static Observation Observe"):
                              fast.index("    internal static void Run")]
    records = fast[fast.index("    private sealed record Enemy"):
                   fast.index("    private static Func")]
    (src / "FrozenQ1.cs").write_text(
        imports + "namespace OfflineSearchHarness;\ninternal static partial class RealCombat\n{\n"
        + records + observe_and_decide + "}\n", encoding="utf-8")
    shutil.copyfile(HERE.parent / "m1-q3/CombatChoices.cs", src / "CombatChoices.cs")
    for filename in ("RealCombat.cs", "ChoiceScope.cs"):
        shutil.copyfile(HERE / filename, src / filename)
    replace(src / "IntegrationProbe.cs", "private static void Load()\n    {",
            "internal static void Load()\n    {\n        if (_loaded) return;")
    replace(src / "IntegrationProbe.cs", '["transitions"] = result.TransitionCount,',
            '["transitions"] = result.TransitionCount, ["expanded_nodes"] = result.ExpandedNodes,'
            ' ["total_expanded_nodes"] = result.TotalExpandedNodes,')
    replace(src / "Program.cs", 'result = cmd.GetProperty("cmd")',
            'if (cmd.GetProperty("cmd").GetString()?.StartsWith("f1_", StringComparison.Ordinal) == true)\n'
            '                {\n                    IntegrationProbe.Load();\n'
            '                    result = OfflineSearchHarness.RealCombat.Run(sim, cmd);\n'
            '                }\n                else result = cmd.GetProperty("cmd")')


if __name__ == "__main__":
    i1.build(i1.ROOT / "logs/m1-f1-build", stage)
