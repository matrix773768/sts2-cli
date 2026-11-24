"""Build an isolated SV1 host and an instrumented copy of II-K.3B."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRE = runpy.run_path(str(HERE.parent / "m1-pre0b/build_host.py"))
edit = PRE["edit"]
SOLVER = ROOT / "logs/iik3b-solver"
BASE_SOLVER = "b4db8cae5abada95a3a51caac31bbae9f356fb553949b3c7d4b14ea10d181c53"
GAME = "62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3"
STEAM = Path.home() / "Desktop/STEAM/steamapps"
RITSU = STEAM / "workshop/content/2868840/3747602295"
DATA = STEAM / "common/Slay the Spire 2/data_sts2_windows_x86_64"


def digest(path):
    with path.open("rb") as stream:
        checksum = sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
        return checksum.hexdigest()


def instrument(src):
    sim = src / "Engine/InCombat/Simulation"
    shutil.copyfile(HERE / "SearchProbe.cs", sim / "SearchProbe.cs")
    draw = sim / "CombatPredictionSimulator.CardPile.cs"
    edit(draw, "            PredictedCard card = state.DrawPile.Cards[0];",
         '            SearchProbe.BeforeDraw(this, player, drawCount - index, fromHandDraw);\n'
         "            PredictedCard card = state.DrawPile.Cards[0];")
    # Guard the stream at its source, including hooks and calls with no eventual RNG advance.
    rng = sim / "CombatPredictionRngSet.cs"
    for field, kind in {
        "Shuffle": "shuffle", "CombatCardGeneration": "card_generation",
        "CombatPotionGeneration": "potion_generation", "CombatCardSelection": "card_selection",
        "CombatEnergyCosts": "energy_cost", "CombatTargets": "random_target",
        "CombatOrbGeneration": "orb_generation", "Niche": "other_rng",
    }.items():
        attr = "_" + field[0].lower() + field[1:]
        edit(rng, f"public Rng {field} => {attr}.Mutable;",
             f'public Rng {field} {{ get {{ SearchProbe.Stop("{kind}"); return {attr}.Mutable; }} }}')
    edit(rng, "        Stream stream = _nonCombatGeneration[player];",
         '        SearchProbe.Stop("persistent_generation");\n        Stream stream = _nonCombatGeneration[player];')
    edit(sim / "CombatPredictionSimulator.AutoPlayContinuation.cs", "            PredictedCard? card = position switch",
         '            if (!state.DrawPile.IsEmpty) SearchProbe.Stop("autoplay_from_draw");\n'
         "            PredictedCard? card = position switch")
    edit(src / "Search/CardChoiceResolution.cs",
         "                    var top = owner.DrawPile.Cards.Take(chant.DynamicVars.Cards.IntValue).ToArray();",
         '                    if (!owner.DrawPile.IsEmpty) SearchProbe.Stop("reveal_from_draw");\n'
         "                    var top = owner.DrawPile.Cards.Take(chant.DynamicVars.Cards.IntValue).ToArray();")
    resolver = src / "Prediction/MonsterRandomBranchResolver.cs"
    edit(resolver, "        float roll = rng.NextFloat(total);",
         '        if (total > 0 && (weighted[0].Weight <= 0 || weighted.Skip(1).Any(entry => entry.Weight > 0)))\n'
         '            CombatSolver.Engine.InCombat.Simulation.SearchProbe.Stop("monster_multi_outcome_rng");\n'
         "        float roll = rng.NextFloat(total);")
    edit(src / "Prediction/MonsterMoveEffects.cs", "        int selected = simulator.Rng.MonsterAi.NextItem(candidates);",
         '        if (candidates.Length > 1) SearchProbe.Stop("random_enemy_effect");\n'
         "        int selected = simulator.Rng.MonsterAi.NextItem(candidates);")
    edit(src / "Search/SimulatedCombatState.MonsterAi.cs", "        return lastState.GetNextState(creature, rng);",
         '        if (lastState is RandomBranchState) SearchProbe.Stop("unqualified_enemy_state_log");\n'
         "        return lastState.GetNextState(creature, rng);")
    edit(sim / "CombatPredictionSimulator.cs", "        GuardOrdinaryCardContinuationFork();",
         "        using var sv1Fork = SearchProbe.MeasureFork();\n        GuardOrdinaryCardContinuationFork();")


def build(out, game_data, ritsu):
    if (digest(SOLVER / "bin/CombatSolver.dll") != BASE_SOLVER
            or any(digest(path / "sts2.dll") != GAME for path in (ROOT / "lib", game_data))):
        raise ValueError("Unexpected II-K.3B or STS2 artifacts")
    out.mkdir(parents=True, exist_ok=False)
    source = out / "solver"
    shutil.copytree(SOLVER / "source/src", source / "src")
    shutil.copyfile(SOLVER / "source/CombatSolver.csproj", source / "CombatSolver.csproj")
    instrument(source / "src")
    env = os.environ | {"DOTNET_CLI_HOME": str(ROOT / "logs/dotnet-home"),
                        "NUGET_PACKAGES": str(ROOT / "logs/nuget-packages")}
    binary = out / "solver-bin"
    subprocess.run(["dotnet", "build", str(source / "CombatSolver.csproj"), "-c", "Release",
                    "-p:CopyModOnBuild=false", "-p:OS=Unix", "-p:NuGetAudit=false",
                    f"-p:Sts2DataDir={game_data}", f"-p:RitsuWorkshopRoot={ritsu}",
                    "-p:Version=0.51.5-iik.3b.sv1", "-o", str(binary)],
                   env=env, check=True, timeout=180)

    def stage(src):
        PRE["stage"](src)
        project = src / "Sts2Headless.csproj"
        edit(project, str(PRE["pre0"]["base"].SOLVER), str(binary / "CombatSolver.dll"))
        shutil.copyfile(HERE / "TurnGraph.cs", src / "TurnGraph.cs")
        menu = src / "NoslPublicEpisode.cs"
        edit(menu, "object? decision = null)", "object? decision = null, bool previewMoves = true)")
        edit(menu, "var preview = ImmediatePreview(sim, card, type == TargetType.AnyEnemy ? entity : null);",
             "var preview = previewMoves ? ImmediatePreview(sim, card, type == TargetType.AnyEnemy ? entity : null) : null;")
        synthetic = src / "SyntheticCombat.cs"
        edit(synthetic, "        if (spec.Relics.Any(r => !player.Relics.Any(native => native.Id.Entry == r))",
             """        bool fixture = request.TryGetProperty("sv1_fixture", out var fixtureOptions);
        if (spec.Relics.Any(r => !player.Relics.Any(native => native.Id.Entry == r)
                && !(fixture && r is "NUNCHAKU" or "TUNING_FORK" or "LANTERN" or "BAG_OF_PREPARATION"))""")
        edit(synthetic, "        WaitForActionExecutor();\n        return DetectDecisionPoint();",
             """        WaitForActionExecutor();
        if (fixture && fixtureOptions.TryGetProperty("relic_count", out var count))
            foreach (var relic in player.Relics)
            {
                string? member = relic.Id.Entry == "NUNCHAKU" ? "AttacksPlayed" :
                    relic.Id.Entry == "TUNING_FORK" ? "SkillsPlayed" : null;
                if (member != null)
                    relic.GetType().GetProperty(member, System.Reflection.BindingFlags.Public |
                        System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!
                        .SetValue(relic, count.GetInt32());
            }
        if (fixture && fixtureOptions.TryGetProperty("enemy_hp", out var hp))
            CreatureCmd.SetCurrentHp(CombatManager.Instance.DebugOnlyGetState()!.Enemies.Single(), hp.GetInt32())
                .GetAwaiter().GetResult();
        return DetectDecisionPoint();""")
        edit(src / "IntegrationProbe.cs", '        if (command == "i1_n2_close")',
             '        if (command == "i1_sv1_graph")\n'
             '            return (_episode ?? throw new InvalidOperationException("Reset first")).TurnGraph(cmd);\n'
             '        if (command == "i1_sv1_state")\n'
             '            return new() { ["type"] = "sv1_state", ["episode"] = (_episode ?? throw new InvalidOperationException("Reset first")).InteractiveView() };\n'
             '        if (command == "i1_n2_close")')

    PRE["pre0"]["base"].build(out / "host", stage)
    host_bin = out / "host/Headless/bin/Debug/net9.0"
    files = [binary / "CombatSolver.dll", host_bin / "OfflineSearchHarness.dll", host_bin / "GodotSharp.dll"]
    identity = dict(version="0.51.5-iik.3b.sv1", base_solver=BASE_SOLVER, game=GAME,
                    artifacts={str(path.relative_to(out).as_posix()): digest(path) for path in files},
                    sources={path.name: digest(path) for path in sorted(HERE.glob("*")) if path.is_file()},
                    ritsu=str(ritsu))
    (out / "build.json").write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--game-data", type=Path, default=DATA)
    parser.add_argument("--ritsu", type=Path, default=RITSU)
    args = parser.parse_args()
    build(args.output.resolve(), args.game_data.resolve(), args.ritsu.resolve())
