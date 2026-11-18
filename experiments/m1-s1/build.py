"""Stage a synthetic-only native host alongside the frozen F3B engine."""
import importlib.util
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("s1_f3b_build", HERE.parent / "m1-f3b/build.py")
f3b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f3b)
HOST = "m1-s1-build"


def stage(src):
    f3b.stage(src)
    shutil.copyfile(HERE / "SyntheticCombat.cs", src / "SyntheticCombat.cs")
    f3b.f3a.f2.replace(src / "Program.cs",
        '                if (cmd.GetProperty("cmd").GetString()?.StartsWith("f1_", StringComparison.Ordinal) == true)',
        '''                var kind = cmd.GetProperty("cmd").GetString();
                if (kind == "synthetic_start")
                    result = sim.StartSyntheticCombat(cmd);
                else if (kind == "synthetic_snapshot")
                {
                    IntegrationProbe.Load();
                    result = sim.SyntheticSnapshot();
                }
                else if (kind is "start_run" or "load_save" or "write_continue_save" or
                    "enter_room" or "set_player" or "set_draw_order" or "get_map" ||
                    kind == "quit" && cmd.TryGetProperty("path", out _) ||
                    kind == "action" && cmd.GetProperty("action").GetString() is not
                        ("play_card" or "end_turn" or "select_cards" or "skip_select" or "use_potion"))
                    result = new() { ["type"] = "error", ["message"] = "Synthetic host only supports isolated combat" };
                else if (kind?.StartsWith("f1_", StringComparison.Ordinal) == true)''')


if __name__ == "__main__":
    i1 = f3b.f3a.f2.f1.i1
    i1.build(i1.ROOT / "logs" / HOST, stage)
