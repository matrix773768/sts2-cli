"""Build an isolated experimental PRE0 host from the pinned II-K.4B source lineage."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
EXPERIMENTS = HERE.parent
reward = runpy.run_path(str(EXPERIMENTS / "m1-nosl3c-iih/build_reward_host.py"))
base = reward["COMPLETION"]["IIG"]["BASE"]["BASE"]["BASE"]["BASE"]["BINDING"].b1b.b1a.i1


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(f"Unexpected anchor in {path}: {old}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def stage(src, fused=True):
    reward["stage"](src)
    stubs = src.parent / "GodotStubs"
    current = base.ROOT / "src/GodotStubs"
    for name in ("Core.cs", "Types.cs"):
        text = (current / name).read_text(encoding="utf-8")
        if name == "Core.cs":
            text = text.replace("    public enum InternalMode",
                "    public Collections.Array<Node> FindChildren(string pattern, string type, bool recursive, bool owned) => new();\n\n"
                "    public enum InternalMode", 1)
            text += '\npublic static class DisplayServer { public static string GetName() => "headless"; }\n'
        (stubs / name).write_text(text, encoding="utf-8")
    edit(src / "SyntheticCombat.cs",
         "encounter.RoomType != RoomType.Monster || !acts[actIndex]",
         "encounter.RoomType is not (RoomType.Monster or RoomType.Elite or RoomType.Boss) || !acts[actIndex]")
    edit(src / "RootWorker.cs", "internal void ProbeReset()", "internal void ProbeReset(bool abandon = false)")
    edit(src / "RootWorker.cs", "_runState?.CurrentRoom is not MapRoom",
         "(abandon ? _runState?.CurrentRoom is not CombatRoom : _runState?.CurrentRoom is not MapRoom)")
    edit(src / "RootWorker.cs", "|| _combatTurnTimedOut || CombatManager.Instance.IsInProgress",
         "|| _combatTurnTimedOut || !abandon && CombatManager.Instance.IsInProgress")
    edit(src / "RootWorker.cs", "CleanUp(graceful: true)", "CleanUp(graceful: !abandon)")
    edit(src / "Program.cs", 'else if (kind == "b1a_reset")',
         'else if (kind is "b1a_reset" or "pre0_abandon")')
    edit(src / "Program.cs", "sim.ProbeReset();", 'sim.ProbeReset(abandon: kind == "pre0_abandon");')

    if not fused:
        return
    start = """else if (kind == "pre0_start")
                {
                    var opened = sim.StartSyntheticCombat(cmd);
                    if (!Equals(opened.GetValueOrDefault("decision"), "combat_play"))
                        result = opened;
                    else
                    {
                        IntegrationProbe.Load();
                        var source = OfflineSearchHarness.RealCombat.Run(sim,
                            JsonSerializer.SerializeToElement(new { cmd = "f1_begin" }));
                        var reset = JsonSerializer.SerializeToElement(new {
                            cmd = "i1_n2_reset", arm = "A", cap = cmd.GetProperty("cap").GetInt32(),
                            potions = false, rejected = Array.Empty<string>(),
                        });
                        result = Equals(source.GetValueOrDefault("type"), "error")
                            ? source : IntegrationProbe.Run(sim, reset);
                    }
                }
                """
    edit(src / "Program.cs", 'else if (kind == "synthetic_start")',
         start + 'else if (kind == "synthetic_start")')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--separate-root-rpc", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    fused = not args.separate_root_rpc
    base.build(output, lambda src: stage(src, fused))
    binary = output / "Headless/bin/Debug/net9.0"
    identity = dict(version="PRE0-host.v2" if fused else "PRE0-host.v1", artifacts={
        name: {"sha256": sha256((binary / name).read_bytes()).hexdigest()}
        for name in ("OfflineSearchHarness.dll", "GodotSharp.dll")})
    (output / "build.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
