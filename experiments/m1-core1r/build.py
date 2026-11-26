"""Build an isolated public-draw probe and resident tactical command."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from time import perf_counter

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASE=ROOT/"logs/n4b-host-v2"
SV=ROOT/"logs/m1-sv4a-host"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def source_sha(p):
    return hashlib.sha256(p.read_bytes().replace(b"\r\n",b"\n")).hexdigest()

def replace(path,before,after):
    text=path.read_text(encoding="utf-8-sig")
    if text.count(before)!=1:
        raise ValueError((path,before))
    path.write_text(text.replace(before,after),encoding="utf8")


def build(out,prior=None):
    t=perf_counter()
    identity=json.loads((BASE/"build.json").read_bytes())
    for p,h in identity["artifacts"].items():
        assert sha(BASE/p)==h
    assert sha(SV/"solver-bin/CombatSolver.dll")==identity["artifacts"]["solver-bin/CombatSolver.dll"]
    out.mkdir(parents=True,exist_ok=False)
    solver=out/"solver"
    shutil.copytree(SV/"solver/src",solver/"src")
    shutil.copyfile(SV/"solver/CombatSolver.csproj",solver/"CombatSolver.csproj")
    sim=solver/"src/Engine/InCombat/Simulation"
    probe=sim/"SearchProbe.cs"
    replace(probe,"internal sealed class SearchProbe","internal sealed partial class SearchProbe")
    replace(probe,"        probe.Draw ??= new","        if (probe.TurnDraw != null) { probe.TurnDraw.Draw(sim, player, remaining); return; }\n        probe.Draw ??= new")
    shutil.copyfile(HERE/"PublicDraw.cs",sim/"PublicDraw.cs")
    replace(sim/"CombatPredictionSimulator.CardPile.cs","        shuffledCards.StableShuffle(Rng.Shuffle, this);",
            "        if (!SearchProbe.PublicShuffle(this, player, shuffledCards))\n            shuffledCards.StableShuffle(Rng.Shuffle, this);")
    replay=solver/"src/Search/CombatBeamSolver.Expansion.Replay.cs"
    replace(replay,"    private SimulationSnapshot Replay(","    internal SimulationSnapshot TacticalFork(SimulationSnapshot s) => Replay([], s, s.Turn);\n\n    private SimulationSnapshot Replay(")
    shutil.copytree(BASE/"host",out/"host",ignore=shutil.ignore_patterns("obj","bin"))
    host=out/"host/Headless"
    project=host/"Sts2Headless.csproj"
    replace(project,str(SV/"solver-bin/CombatSolver.dll"),str(out/"solver-bin/CombatSolver.dll"))
    replace(host/"IntegrationProbe.cs",'        if (command == "i1_sv1_graph")',
            '        if (command == "i1_core1r")\n            return (_episode ?? throw new InvalidOperationException("Reset first")).Tactical(cmd);\n        if (command == "i1_sv1_graph")')
    shutil.copyfile(HERE/"Tactical.cs",host/"Tactical.cs")
    replace(host/"NoslPublicEpisode.cs","nunchaku = PublicNunchakuCount(sim),",
            'nunchaku = PublicNunchakuCount(sim),\n            tuning_fork = combat.RelicsOf(_player)'
            '.Where(r => r.Id.Entry == "TUNING_FORK").Select(r => (int?)(combat.ReadRelicCounter(sim,r)'
            ' % r.DynamicVars.Cards.IntValue)).SingleOrDefault(),\n'
            '            order_hooks = combat.EffectivePowers().Where(p => p.IsVisible && '
            '(p.Owner == _player.Creature || targets.Contains(p.Owner))).Select(p => new '
            '{ owner = Array.IndexOf(targets,p.Owner), id = p.Id.Entry }).OrderBy(p => p.owner)'
            '.ThenBy(p => p.id,StringComparer.Ordinal).ToArray(),')
    catalog=HERE/"belief_cards.json"
    values=json.loads(catalog.read_bytes())
    replace(host/"Tactical.cs","/* public belief catalog */",", ".join(map(json.dumps,values)))
    identity["sources"][catalog.name]=source_sha(catalog)
    env=os.environ|dict(DOTNET_CLI_HOME=str(out),NUGET_PACKAGES=str(ROOT/"logs/nuget-packages"))
    steam=Path.home()/"Desktop/STEAM/steamapps"
    if prior:
        source=json.loads((prior/"build.json").read_bytes())
        assert source["sources"]["PublicDraw.cs"]==source_sha(HERE/"PublicDraw.cs")
        assert source["artifacts"]["solver-bin/CombatSolver.dll"]==sha(prior/"solver-bin/CombatSolver.dll")
        for path in (solver/"src").rglob("*.cs"):
            assert source_sha(path)==source_sha(prior/"solver"/path.relative_to(solver))
        shutil.copytree(prior/"solver-bin",out/"solver-bin")
    with (out/"build.log").open("w",encoding="utf8") as log:
        for args in ([str(solver/"CombatSolver.csproj"),"-c","Release","-p:CopyModOnBuild=false","-p:OS=Unix",
                      f"-p:Sts2DataDir={steam/'common/Slay the Spire 2/data_sts2_windows_x86_64'}",
                      f"-p:RitsuWorkshopRoot={steam/'workshop/content/2868840/3747602295'}",
                      "-o",str(out/"solver-bin")],[str(project)]):
            if prior and args[0]!=str(project): continue
            subprocess.run(["dotnet","build",*args,"-p:NuGetAudit=false","--verbosity","quiet"],env=env,
                           stdout=log,stderr=subprocess.STDOUT,timeout=240,check=True)
    identity["artifacts"]={p:sha(out/p) for p in identity["artifacts"]}
    identity["sources"].update({p.name:source_sha(p) for p in HERE.glob("*.cs")})
    identity["build_seconds"]=perf_counter()-t
    (out/"build.json").write_text(json.dumps(identity,indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    p.add_argument("--solver-build",type=Path)
    a=p.parse_args()
    build(a.out.resolve(),a.solver_build)
