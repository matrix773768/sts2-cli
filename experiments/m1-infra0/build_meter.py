"""Build only the instrumented host. Retain the exact frozen Solver and Godot assemblies."""
from infra_assets import BIN, ROOT, sha
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

def build(source):
    frozen = ROOT/"logs/core5c-host"
    folder = ROOT/"logs/infra0-profile-host"
    folder.mkdir(exist_ok=False)
    shutil.copytree(frozen/"solver-bin", folder/"solver-bin")
    host = folder/"host/Headless"
    host.mkdir(parents=True)
    pdb = (frozen/"host"/BIN/"OfflineSearchHarness.pdb").read_bytes()
    original = source/"logs/core5c-host/host/Headless"
    for file in original.glob("*.cs"):
        if bytes.fromhex(sha(file)) not in pdb:
            raise ValueError(f"Source checksum missing from frozen PDB: {file}")
        shutil.copyfile(file, host/file.name)
    shutil.copyfile(Path(__file__).with_name("InfraMeter.cs"), host/"InfraMeter.cs")
    project = ET.parse(original/"Sts2Headless.csproj")
    for group in project.findall("ItemGroup"):
        for ref in list(group):
            if ref.tag == "ProjectReference":
                group.remove(ref)
                ET.SubElement(group,"Reference",Include="GodotSharp", HintPath=str(frozen/"host"/BIN/"GodotSharp.dll"))
            elif ref.tag == "Reference":
                name = ref.attrib["Include"] + ".dll"
                target = folder/"solver-bin"/name if name=="CombatSolver.dll" else ROOT/"lib"/name
                if "HintPath" in ref.attrib:
                    ref.set("HintPath",str(target))
                else:
                    ref.find("HintPath").text = str(target)
    proj = host/"Sts2Headless.csproj"
    project.write(proj,encoding="utf-8")
    def edit(file,pairs):
        p=host/file
        body=p.read_text(encoding="utf-8-sig")
        for old,new in pairs:
            if body.count(old)!=1:
                raise ValueError((file,old))
            body=body.replace(old,new)
        p.write_text(body,encoding="utf8")
    edit("Program.cs", [
        ("string? line;", 'AppDomain.CurrentDomain.ProcessExit += (_,_) => InfraMeter.Save(); InfraMeter.Warmup("ready");\n        string? line;'),
        ("var cmd = JsonSerializer.Deserialize", "InfraMeter.Start(); var cmd = JsonSerializer.Deserialize"),
        ('if (kind == "b1b_fault_delay")','InfraMeter.Parsed(kind ?? "unknown"); if (kind == "b1b_fault_delay")'),
        ('result["_b1a_ms"]', 'InfraMeter.Handled(); result["_b1a_ms"]'),
        ("Console.Out.WriteLine(JsonSerializer.Serialize(data, JsonOpts));",
         'var start=InfraMeter.Now; var json=JsonSerializer.Serialize(data,JsonOpts); InfraMeter.Add("serialize_ticks",InfraMeter.Now-start); Console.Out.WriteLine(json);')])
    edit("Tactical.cs", [
        ("owner._pre0bSolver!.TacticalFork(initial)", 'InfraMeter.Measure("fork",()=>owner._pre0bSolver!.TacticalFork(initial))'),
        ("owner._law.Fork()", 'InfraMeter.Measure("belief_fork",()=>owner._law.Fork())'),
        ("session.Play(action);", 'InfraMeter.Step(end?"settle_end":"settle_play",()=>session.Play(action));'),
        ("session.Play(move.Plan);", 'InfraMeter.Step("graph_play",()=>session.Play(move.Plan));'),
        ("{s=prior.State;bag=prior.Law;continue;}", '{InfraMeter.Add("batch_cached_edge",1);s=prior.State;bag=prior.Law;continue;}')])
    edit("Strategic.cs", [
        ("t.AtC=(sim,player,turn,draw,willShuffle,sideStarted,extra)=>{", "t.AtC=(sim,player,turn,draw,willShuffle,sideStarted,extra)=>{ var tick=InfraMeter.Now;"),
        ('if(stop) SearchProbe.Stop("strategic_c");', 'InfraMeter.Add("C_export_ticks",InfraMeter.Now-tick); InfraMeter.Add("C_exports",1); if(stop) SearchProbe.Stop("strategic_c");')])
    edit("InteractiveEpisode.cs", [
        ('InteractiveInvoke("Play", _episodeMenu![index].Action);','InfraMeter.Step("live_"+_episodeMenu![index].Action.Kind,()=>InteractiveInvoke("Play", _episodeMenu![index].Action));'),
        ('else InteractiveInvoke("Select", _selection.ToArray());','else InfraMeter.Step("live_select",()=>InteractiveInvoke("Select", _selection.ToArray()));')])
    edit("Reference.cs", [
        ('if (!choice) session.Play(_episodeMenu![index].Action);', 'if (!choice) InfraMeter.Step("reference_"+_episodeMenu![index].Action.Kind,()=>session.Play(_episodeMenu![index].Action));'),
        ("var seed=start", 'InfraMeter.Add("prefix_hit_length/"+start,1); var seed=start'),
        ("_pre0bSolver!.TacticalFork(seed)", 'InfraMeter.Measure("fork",()=>_pre0bSolver!.TacticalFork(seed))'),
        ("start==0?_law.Fork():referencePrefixes[keys[start-1]].Law.Fork()", 'InfraMeter.Measure("belief_fork",()=>(start==0?_law:referencePrefixes[keys[start-1]].Law).Fork())'),
        ("calls++;",'calls++; InfraMeter.Add(choice?"replay_choice":"replay_action",1);'),
        ("referencePrefixes.Remove(oldest);",'referencePrefixes.Remove(oldest); InfraMeter.Add("evictions",1);'),
        ("(_pre0bSolver.TacticalFork(current),law.Fork())",'(InfraMeter.Measure("cache_fork",()=>_pre0bSolver.TacticalFork(current)),InfraMeter.Measure("belief_fork",()=>law.Fork()))'),
        ("root.ReleaseSimulator();",'var tick=InfraMeter.Now; root.ReleaseSimulator(); InfraMeter.Add("release_ticks",InfraMeter.Now-tick);')])
    env=os.environ|{k:str(folder/d) for k,d in {"DOTNET_CLI_HOME":"cli","NUGET_PACKAGES":"nuget","TEMP":"temp","TMP":"temp"}.items()}
    (folder/"temp").mkdir()
    feed = folder/"feed"
    feed.mkdir()
    for name in ("microsoft.aspnetcore.app.ref","microsoft.netcore.app.ref","microsoft.windowsdesktop.app.ref","microsoft.netcore.app.host.win-x64"):
        shutil.copyfile(source/f"logs/nuget-packages/{name}/9.0.23/{name}.9.0.23.nupkg",feed/f"{name}.9.0.23.nupkg")
    env.update(DOTNET_GENERATE_ASPNET_CERTIFICATE="false", DOTNET_CLI_TELEMETRY_OPTOUT="1",DOTNET_NOLOGO="1")
    start=time.perf_counter()
    subprocess.run(["dotnet","build",str(proj),"--source",str(feed),"-p:NuGetAudit=false","--disable-build-servers","-m:1","--verbosity","quiet"],env=env,check=True)
    identity=json.loads((frozen/"build.json").read_bytes())
    identity.update(build_seconds=time.perf_counter()-start,infra_parent=identity["artifacts"].copy())
    identity["artifacts"]={k:sha(folder/k) for k in identity["artifacts"]}
    (folder/"build.json").write_text(json.dumps(identity,indent=2))

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("source",type=Path)
    build(parser.parse_args().source.resolve())
