"""Build a private OfflineSearchHarness overlay from the HK0 source archive."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PIN = "131d10ae4499b56332787af61fe4a9306e65860f"
ARCHIVE_SHA = "3aa49546ccf0bad704c2cfd77182a9d311d88622196cbdece9a7a1e9c51199b3"


def checksum(path):
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def recipe_source():
    recipe = ROOT / "logs/m1-sv4a-host/host/Headless/SyntheticCombat.cs"
    if checksum(recipe) != "faa2ab96fa18a05fca094fbd45a977a23604413abfd7eea8e33f23ae766f9adb":
        raise ValueError("Frozen SV4A recipe source differs")
    text = recipe.read_text(encoding="utf-8")
    prefix = text[:text.index("public partial class RunSimulator")]
    prefix = prefix.replace("namespace Sts2Headless;", "namespace OfflineSearchHarness;")
    body = text[text.index("    private static readonly JsonSerializerOptions SyntheticJson"):
                text.index("    // The game serializes RNG")]
    body = body.replace("internal Dictionary<string, object?> StartSyntheticCombat(JsonElement request)",
                        "internal static CombatState Open(MainLoopContext loop, JsonElement request)")
    start = body.index("        if (_runState")
    body = body[:start] + """
        var spec = request.GetProperty("spec").Deserialize<SyntheticCombatSpec>(SyntheticJson);
""" + body[body.index("        if (spec is null", start):]
    body = body.replace('return Error(', 'throw new InvalidOperationException(')
    body = body.replace('var player = CreatePlayer(spec.Character) ?? throw new ArgumentException("Unknown character");',
                        'var player = Player.CreateForNewRun(RealCombatDriver.ResolveModel(ModelDb.AllCharacters, spec.Character, "character"), UnlockState.all, 1uL);')
    body = body.replace("encounter.RoomType != RoomType.Monster || !acts[0]",
                        "encounter.RoomType is not (RoomType.Monster or RoomType.Elite or RoomType.Boss) || !acts[0]")
    body = body.replace("_runState = RunState.", "var run = RunState.").replace("_runState", "run")
    start = body.index("        _cardSelectorScope")
    body = body[:start] + body[body.index("        manager.FinalizeStartingRelics", start):]
    body = body[:body.index("        manager.EnterRoomDebug")] + """
        loop.RunUntilCompleted(manager.EnterRoomDebug(encounter.RoomType, MapPointType.Unassigned,
            encounter, showTransition: false), TimeSpan.FromSeconds(30), "HK1A native room");
        return OfflineCombat.WaitForPlayableCombat(loop);
    }
"""
    snapshot = text[text.index("    // The game serializes RNG"):].replace(
        "internal Dictionary<string, object?> SyntheticSnapshot()", "internal static Dictionary<string, object?> Identity(CombatState combat)")
    snapshot = snapshot[:snapshot.index("    internal Dictionary<string, object?> RewardAuditSnapshot")] + snapshot[snapshot.index("    internal static Dictionary<string, object?> Identity"):]
    start = snapshot.index("        var run")
    end = snapshot.index("        var pcs")
    snapshot = snapshot[:start] + "        var run = combat.RunState;\n        var player = run.Players.Single();\n" + snapshot[end:]
    snapshot = snapshot.replace('["continuation"] = ContinuationStamp.CaptureLive(combat).StateText,',
        '''["opening"] = OfflineCombat.DescribeRoot(combat),
            ["continuation"] = ContinuationStamp.CaptureLive(combat).StateText,
            ["potions"] = player.PotionSlots.Select(p => p?.Id.Entry).ToArray(),
            ["gold"] = player.Gold,''')
    return ("using MegaCrit.Sts2.Core.Entities.Players;\nusing MegaCrit.Sts2.Core.Unlocks;\n"
            + prefix + "internal static class Hk1Root\n{\n" + body + snapshot)


def build(output, archive, steam):
    if checksum(archive) != ARCHIVE_SHA:
        raise ValueError("Upstream archive differs from HK0")
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as source:
        source.extractall(output)
    tree = output / f"CombatSolver-{PIN}"
    harness = tree / "tools/search/OfflineSearchHarness"
    (harness / "Hk1Root.cs").write_text(recipe_source(), encoding="utf-8")
    oracle = HERE / "Oracle.cs"
    (harness / oracle.name).write_bytes(oracle.read_bytes())
    program = harness / "Program.cs"
    text = program.read_text(encoding="utf-8")
    anchor = '        if (rawArgs.Length == 1'
    text = text.replace(anchor, '        if (rawArgs.Length == 6 && rawArgs[0] == "--hk1a")\n'
                        '            return Hk1Oracle.Run(rawArgs[1..]);\n' + anchor, 1)
    program.write_text(text, encoding="utf-8")
    env = os.environ | {"NUGET_PACKAGES": str(ROOT / "logs/nuget-packages"),
                        "DOTNET_CLI_HOME": str(output / "dotnet-home"),
                        "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false"}
    flags = ["-c", "Release", "-m:1", "-p:CopyModOnBuild=false", "-p:UseSharedCompilation=false",
             "-p:NuGetAudit=false", f"-p:SteamRoot={steam}"]
    with (output / "build.log").open("wb") as log:
        for project in (tree / "CombatSolver.csproj", harness / "OfflineSearchHarness.csproj"):
            subprocess.run(["dotnet", "build", str(project), *flags], cwd=tree, env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
    freeze_build(output, tree)


def freeze_build(output, tree):
    dll = next((tree / ".local/tool-build/OfflineSearchHarness/bin").rglob("OfflineSearchHarness.dll"))
    solver = tree / ".godot/mono/temp/bin/Release/CombatSolver.dll"
    config = next(dll.parent.glob("*.runtimeconfig.json"))
    properties = json.loads(config.read_text(encoding="utf-8"))["runtimeOptions"]["configProperties"]
    game = Path(properties["Sts2DataDir"])
    ritsu = [Path(properties[name]) for name in ("RitsuLibCompatDir", "RitsuLibSharedDir")]
    runtime = ROOT / "logs/m0-v5/dotnet9"
    deps = [dll, solver, *dll.parent.glob("*.json"), *game.glob("*.dll"),
            *(p for directory in ritsu for p in directory.glob("*.dll")),
            runtime / "dotnet.exe", *runtime.glob("host/fxr/9.0.7/*.dll"),
            *runtime.glob("shared/Microsoft.NETCore.App/9.0.7/*.dll")]
    manifest = {"version": f"hk1a-final-locked-hp-v1-{PIN}", "dll": str(dll), "tree": str(tree),
                "adapter": {str(p): checksum(p) for p in
                            (HERE / "Oracle.cs", HERE / "hk1a_build.py",
                             ROOT / "logs/m1-sv4a-host/host/Headless/SyntheticCombat.cs")},
                "artifacts": {str(p): checksum(p) for p in deps}}
    (output / "build.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--steam", type=Path, required=True)
    args = parser.parse_args()
    build(args.output.resolve(), args.archive.resolve(), args.steam.resolve())
