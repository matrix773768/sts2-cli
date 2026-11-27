"""Build the pinned HotDraw solver with an observer at the actual strategic C boundary."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from campaign import ROOT,HERE,sha

PIN="131d10ae4499b56332787af61fe4a9306e65860f"
def build(tag):
    archive=ROOT.parent/"hk0-isolated-131d10a/upstream.zip"
    if sha(archive)!="3aa49546ccf0bad704c2cfd77182a9d311d88622196cbdece9a7a1e9c51199b3":raise ValueError("Upstream archive")
    src=ROOT.parent/"sts2-cli/logs"
    old=json.loads((src/"hotdraw-structures-build-03/build.json").read_bytes())
    config=json.loads(Path(old["dll"]).with_suffix(".runtimeconfig.json").read_bytes())
    game=Path(config["runtimeOptions"]["configProperties"]["Sts2DataDir"])
    if sha(game/"sts2.dll")!=old["game_sha256"]:raise ValueError("Game version")
    out=ROOT/"logs"/("infra1h-hot-"+tag)
    out.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as z:z.extractall(out)
    tree=out/("CombatSolver-"+PIN)
    spec=importlib.util.spec_from_file_location("hotbuild_base",HERE.parent/"hotdraw/build.py")
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
    harness=base.instrument(tree)
    sim=tree/"src/HotKernel/Sim"
    turn=sim/"HotCombatEngine.Turn.cs"
    anchor="            DrawCards(ref s, ref cold, rules, scratch, drawCount, fromHandDraw: true);"
    base.edit(turn,anchor,"            InfraCObserver.BeforeDraw?.Invoke(in s,cold,rules,drawCount);\n"+anchor)
    shutil.copyfile(HERE/"InfraCObserver.cs",sim/"InfraCObserver.cs")
    base.edit(sim/"HotCombatEngine.CardPlay.cs","private static HotCard CreateFreshCard(", "internal static HotCard CreateFreshCard(")
    packages=out/"packages";shutil.copytree(src/"nuget-packages",packages)
    feed=out/"feed";feed.mkdir()
    for pkg in packages.rglob("*.nupkg"):shutil.copyfile(pkg,feed/pkg.name)
    (tree/"NuGet.Config").write_text('<configuration><packageSources><clear/><add key="offline" value="'+str(feed)+'"/></packageSources></configuration>')
    env=os.environ|dict(NUGET_PACKAGES=str(packages),DOTNET_CLI_HOME=str(out/"cli"),DOTNET_NOLOGO="1",DOTNET_CLI_TELEMETRY_OPTOUT="1")
    args=["dotnet","build",tree/"CombatSolver.csproj","-c","Release","-m:1","--disable-build-servers","-p:NuGetAudit=false","-p:CopyModOnBuild=false","-p:SteamRoot="+str(game.parents[3])]
    subprocess.run(args,cwd=tree,env=env,check=True)
    dll=tree/".godot/mono/temp/bin/Release/CombatSolver.dll"
    (out/"manifest.json").write_text(json.dumps(dict(upstream=PIN,archive=sha(archive),solver=str(dll),sha256=sha(dll),game=sha(game/"sts2.dll")),indent=2))
if __name__=="__main__":build(sys.argv[1])
