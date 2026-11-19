"""Extend the isolated B1A host with resource telemetry and a fault probe."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("b1a_build", HERE.parent / "m1-b1a/build_probe.py")
b1a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1a)


def stage(src):
    b1a.stage(src)
    edit = b1a.edit
    first = src / "FirstWin.cs"
    edit(first, "int CumulativeLoss, string Stop", "int CumulativeLoss, int MaxHp, int Gold, string Stop")
    edit(first, "snapshot.CumulativePlayerHpLost, stop",
         "snapshot.CumulativePlayerHpLost, sim.State.GetCreature(_player.Creature).MaxHp, combat.GetPlayerGold(_player), stop")
    quality = src / "QualitySearch.cs"
    edit(quality, "int HpLost, string?[] Potions,", "int HpLost, int MaxHp, int Gold, string?[] Potions,")
    edit(quality, "end.Hp, end.CumulativeLoss, end.Potions, strategy,",
         "end.Hp, end.CumulativeLoss, end.MaxHp, end.Gold, end.Potions, strategy,")
    edit(src / "RootWorker.cs", "    private static string? _initialProgress;", """    private static string? _initialProgress;
    internal static string ProbeInitialProgress() => _initialProgress
        ?? throw new InvalidOperationException("Profile baseline missing");""")
    program = src / "Program.cs"
    edit(program, '                if (kind == "b1a_reset")', '''                if (kind == "b1b_fault_delay")
                {
                    Thread.Sleep(15000);
                    result = new() { ["type"] = "delay_returned" };
                }
                else if (kind == "b1b_initial_profile")
                    result = new() { ["type"] = "profile", ["value"] = RunSimulator.ProbeInitialProgress() };
                else if (kind == "b1a_reset")''')


if __name__ == "__main__":
    b1a.i1.build(b1a.ROOT / "logs/m1-b1b-build", stage)
