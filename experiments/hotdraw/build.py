"""Build a separate research overlay of the HK1A archive."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hk1a"))
from hk1a_build import ARCHIVE_SHA, PIN, ROOT, checksum

GAME_SHA = "62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3"


def edit(path, before, after, *, count=1):
    source = path.read_text(encoding="utf-8")
    if source.count(before) != count:
        raise ValueError(f"Unexpected overlay anchor in {path.name}: {before}")
    path.write_text(source.replace(before, after), encoding="utf-8")


def instrument(tree):
    sim = tree / "src/HotKernel/Sim"
    engine = "HotCombatEngine."
    probe = "global::CombatSolver.HotDraw.Probe"
    card_play = sim / (engine + "CardPlay.cs")
    edit(card_play, "        bool fromHandDraw)\n        => DrawCards(ref s, ref cold, rules, scratch, drawCount, fromHandDraw, out _);",
         "        bool fromHandDraw, [CallerMemberName] string drawSource = \"\")\n"
         "        => DrawCards(ref s, ref cold, rules, scratch, drawCount, fromHandDraw, out _, drawSource);")
    edit(card_play, "        out ushort lastDrawnCardDefId)\n", "        out ushort lastDrawnCardDefId, [CallerMemberName] string drawSource = \"\")\n")
    edit(card_play,
         "                if (!HotPiles.DrawTopToHand(ref s))",
         f"                {probe}.Current?.BeforeDraw(ref s, cold, scratch, fromHandDraw, drawCount - i, drawSource);\n"
         "                if (!HotPiles.DrawTopToHand(ref s))")
    edit(sim / (engine + "CardPlay.cs"),
         "        // STS2 0.113.1 CardPileCmd.AutoPlayFromDrawPile",
         f'        {probe}.Current?.Reject("autoplay_from_draw", nameof(AutoPlayFromDrawPile));\n'
         "        // STS2 0.113.1 CardPileCmd.AutoPlayFromDrawPile")
    piles = sim / "HotPiles.cs"
    edit(piles, "        AddPileCount(ref s, srcPile, -1);",
         f"        {probe}.Current?.BeforeMove(in s, srcIndex, srcPile, dstPile, dstOffsetInPile);\n"
         "        AddPileCount(ref s, srcPile, -1);")
    edit(piles, "        HotRng.UnstableShuffle(buf, ref s.Rng[(int)HotRngStream.Shuffle]);",
         f"        if ({probe}.Current?.BeforeShuffle(in s, buf, rules) != true)\n"
         "            HotRng.UnstableShuffle(buf, ref s.Rng[(int)HotRngStream.Shuffle]);")
    edit(piles, "public static int AddCard(ref CombatHotState s, in HotCard card, HotPileKind dstPile, int dstOffsetInPile)\n    {",
         "public static int AddCard(ref CombatHotState s, in HotCard card, HotPileKind dstPile, int dstOffsetInPile)\n    {\n"
         f'        {probe}.Current?.Reject("generated_instance", nameof(AddCard));')
    edit(piles, "public static void RemoveCard(ref CombatHotState s, int index)\n    {",
         "public static void RemoveCard(ref CombatHotState s, int index)\n    {\n"
         f"        {probe}.Current?.BeforeRemove(in s, index);")
    rng = sim / "HotRng.cs"
    edit(rng, "        rng.Counter++;",
         f"        {probe}.Current?.BeforeRng();\n        rng.Counter++;", count=2)
    choices = sim / (engine + "Choices.cs")
    edit(choices, "        RecordPendingChoiceGroup(scratch, minCount);\n        selected = default;",
         "        RecordPendingChoiceGroup(scratch, minCount);\n"
         f"        if ({probe}.Current is {{ }} research)\n"
         "        {\n"
         "            selected = research.Choose(in s, scratch);\n"
         "            scratch.NeedsChoice = false;\n"
         "            return true;\n"
         "        }\n"
         "        selected = default;", count=3)
    edit(choices, "int compareLimit = Math.Min(emittedCount, emittedCardIndices.Length);",
         f"int compareLimit = {probe}.Current == null ? Math.Min(emittedCount, emittedCardIndices.Length) : 0;")
    edit(choices, "    [MethodImpl(MethodImplOptions.AggressiveInlining)]\n    private static bool AreChoiceEquivalentCards(",
         "    internal static bool EquivalentResearchDraw(in CombatHotState state, HotColdSidecar? cold,\n"
         "        int left, int right)\n"
         "        => AreChoiceEquivalentCards(in state, HotPileKind.Hand, 0, 0,\n"
         "            in state.Cards[left], in state.Cards[right], cold);\n\n"
         "    [MethodImpl(MethodImplOptions.AggressiveInlining)]\n    private static bool AreChoiceEquivalentCards(")
    for path in HERE.glob("*.cs"):
        if path.name != "Harness.cs":
            shutil.copyfile(path, tree / "src/HotKernel" / path.name)

    harness = tree / "tools/search/OfflineSearchHarness"
    shutil.copyfile(HERE / "Harness.cs", harness / "HotDrawHarness.cs")
    edit(harness / "Program.cs", "        if (rawArgs.Length == 1 && rawArgs[0] == \"--check-hot-layout\")",
         "        if (rawArgs.Length == 4 && rawArgs[0] == \"--hotdraw\")\n"
         "            return HotDrawHarness.Run(rawArgs[1], rawArgs[2], rawArgs[3]);\n"
         "        if (rawArgs.Length == 1 && rawArgs[0] == \"--check-hot-layout\")")
    return harness


def build(output, archive, steam, *, extension=None):
    if checksum(archive) != ARCHIVE_SHA:
        raise ValueError("Upstream archive differs from HK1A")
    game = steam / "steamapps/common/Slay the Spire 2/data_sts2_windows_x86_64/sts2.dll"
    if checksum(game) != GAME_SHA:
        raise ValueError("Game DLL differs from HK1A")
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as source:
        source.extractall(output)
    tree = output / f"CombatSolver-{PIN}"
    harness = instrument(tree)
    extension_manifest = extension(tree, harness) if extension else {}
    env = os.environ | {"NUGET_PACKAGES": str(ROOT / "logs/nuget-packages"),
                        "DOTNET_CLI_HOME": str(output / "dotnet-home"),
                        "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false"}
    flags = ["-c", "Release", "-m:1", "-p:CopyModOnBuild=false", "-p:UseSharedCompilation=false",
             "-p:NuGetAudit=false", f"-p:SteamRoot={steam}"]
    with (output / "build.log").open("wb") as log:
        for project in (tree / "CombatSolver.csproj", harness / "OfflineSearchHarness.csproj"):
            subprocess.run(["dotnet", "build", str(project), *flags], cwd=tree, env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
    dll = next((tree / ".local/tool-build/OfflineSearchHarness/bin").rglob("OfflineSearchHarness.dll"))
    solver = tree / ".godot/mono/temp/bin/Release/CombatSolver.dll"
    runtime = ROOT / "logs/m0-v5/dotnet9/dotnet.exe"
    config = dll.with_suffix(".runtimeconfig.json")
    properties = json.loads(config.read_text(encoding="utf-8"))["runtimeOptions"]["configProperties"]
    references = [Path(properties[key]) for key in ("RitsuLibCompatDir", "RitsuLibSharedDir")]
    coreclr = runtime.parent / "shared/Microsoft.NETCore.App/9.0.7/coreclr.dll"
    manifest = {"upstream": PIN, "archive_sha256": ARCHIVE_SHA, "game_sha256": GAME_SHA,
                "dll": str(dll), "harness_sha256": checksum(dll), "runtimeconfig_sha256": checksum(config),
                "solver": str(solver), "solver_sha256": checksum(solver), "coreclr_sha256": checksum(coreclr),
                "runtime": str(runtime), "runtime_sha256": checksum(runtime),
                "adapter": {p.name: checksum(p) for p in sorted(HERE.iterdir()) if p.suffix in {".cs", ".py"}},
                "ritsu": {f"{d.name}/{p.name}": checksum(p) for d in references for p in sorted(d.glob("*.dll"))}}
    (output / "build.json").write_text(json.dumps(manifest | extension_manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--steam", type=Path, required=True)
    args = parser.parse_args()
    build(args.output.resolve(), args.archive.resolve(), args.steam.resolve())
