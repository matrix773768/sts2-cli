"""Build isolated scalar-compatible batch and metering hosts from the verified 0B project and their distinct frozen sources."""
import os
import shutil
import subprocess
import sys
from common import HERE, ROOT, sha, json, charged
from infra_assets import BIN

def build(world, mode):
    metered=mode in ('meter','detail','attribution')
    family = "5e" if world else "5d"
    parent = "core5e-world-host" if world else "core5c-host"
    profile = ROOT/"logs"/("infra0-world-profile" if world else "infra0-profile-host")
    original = ROOT/"logs"/parent
    frozen = json.loads((original/"build.json").read_bytes())
    out = ROOT/"logs"/("infra1a-"+family+("-"+mode))
    out.mkdir(exist_ok=False)
    sources = ROOT.parent/"sts2-cli/logs"/parent/"host/Headless"
    pdb = (original/"host"/BIN/"OfflineSearchHarness.pdb").read_bytes()
    host = out/"host/Headless"
    host.mkdir(parents=True)
    for src in sources.glob("*.cs"):
        if bytes.fromhex(sha(src)) not in pdb:
            raise ValueError(src)
        shutil.copyfile(profile/"host/Headless"/src.name if metered else src, host/src.name)
    if metered:
        shutil.copyfile(profile/"host/Headless/InfraMeter.cs",host/"InfraMeter.cs")
    shutil.copytree(original/"solver-bin",out/"solver-bin")
    for path, digest in frozen["artifacts"].items():
        if sha(original/path)!=digest:raise ValueError(path)
    shutil.copyfile(HERE/"ReferenceBatch.cs",host/"ReferenceBatch.cs")
    for file, old, new in [
        ("Program.cs","private static readonly JsonSerializerOptions JsonOpts","internal static readonly JsonSerializerOptions JsonOpts"),
        ("IntegrationProbe.cs",'if (command == "i1_core5_reference")','if (command == "i1_infra1_reference_batch") return ReferenceBatch(cmd);\n        if (command == "i1_core5_reference")')]:
        file=host/file
        source=file.read_text(encoding="utf-8-sig")
        if source.count(old)!=1:raise ValueError(file)
        file.write_text(source.replace(old,new),encoding="utf8")
    if mode in ("detail","attribution"):
        p=host/"Reference.cs"
        s=p.read_text(encoding="utf-8-sig")
        for old,new in [
            ("var keys=new string", "var keyStart=InfraMeter.Now; var keys=new string"),
            ('InfraMeter.Add("prefix_hit_length/', 'InfraMeter.Add("route_lookup_ticks",InfraMeter.Now-keyStart); InfraMeter.Add("prefix_hit_length/'),
            ("else ObserveNosl(_root, before);",'else InfraMeter.Measure("replay_menu",()=>ObserveNosl(_root,before));'),
            ("state=ObserveNosl(_root,current)",'state=InfraMeter.Measure("reply_projection",()=>ObserveNosl(_root,current))'),
            ("if (choice) InteractiveView();",'if (choice) InfraMeter.Measure("selector_view",()=>InteractiveView());'),
            ("referencePrefixes[oldest].Snapshot.ReleaseSimulator();",'InfraMeter.Step("evict_release",()=>referencePrefixes[oldest].Snapshot.ReleaseSimulator());')]:
            if s.count(old)!=1:raise ValueError(old)
            s=s.replace(old,new)
        p.write_text(s,encoding="utf8")
        p=host/"ReferenceBatch.cs"
        s=p.read_text().replace("results.Add(JsonSerializer.SerializeToElement(episode.Reference(item), Program.JsonOpts));",
            'var value=episode.Reference(item); results.Add(InfraMeter.Measure("item_serialize",()=>JsonSerializer.SerializeToElement(value, Program.JsonOpts)));')
        p.write_text(s,encoding="utf8")
    if mode=="attribution":
        # Keep the external sampling/metadata and every Reference return value.
        # Dispatch is inclusive; the OS resource query occurs after it returns.
        for filename, edits in (
            ("IntegrationProbe.cs", [
                ("var response = Dispatch(sim, cmd);", 'var response = InfraMeter.Measure("dispatch",()=>Dispatch(sim,cmd));'),
                ('process.PeakWorkingSet64;', 'InfraMeter.Measure("process_peak",()=>process.PeakWorkingSet64);')]),
            ("Reference.cs", [
                ("using var session = _pre0bSolver.OpenInteractiveCombat(root);",
                 'using var session = InfraMeter.Measure("interactive_open",()=>_pre0bSolver.OpenInteractiveCombat(root));'),
                ('var knowledge = KnowledgeChoice(before);',
                 'var knowledge = InfraMeter.Measure("replay_knowledge",()=>KnowledgeChoice(before));'),
                ('var draws = edge.GetProperty("draws").Deserialize<string[]>()!;',
                 'var draws = InfraMeter.Measure("draw_decode",()=>edge.GetProperty("draws").Deserialize<string[]>()!);')])):
            path=host/filename
            source=path.read_text(encoding="utf-8-sig")
            for old,new in edits:
                if source.count(old)!=1:raise ValueError((filename,old))
                source=source.replace(old,new)
            path.write_text(source,encoding="utf8")
    project=host/"Sts2Headless.csproj"
    project.write_text((profile/"host/Headless"/project.name).read_text().replace(str(profile),str(out)),encoding="utf8")
    env=os.environ | dict(DOTNET_CLI_HOME=str(out/"cli"),NUGET_PACKAGES=str(out/"packages"),
        DOTNET_GENERATE_ASPNET_CERTIFICATE="false",DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1")
    subprocess.run(["dotnet","build",project,"--source",profile/"feed","-p:NuGetAudit=false","--disable-build-servers","-m:1","-v:q"],env=env,check=True)
    artifacts={k:sha(out/k) for k in frozen["artifacts"]}
    for k in artifacts:
        if not k.endswith("OfflineSearchHarness.dll") and artifacts[k]!=frozen["artifacts"][k]:raise ValueError(k)
    (out/"build.json").write_text(json.dumps(frozen | dict(infra_parent=frozen["artifacts"],artifacts=artifacts),indent=2))

if __name__=="__main__":
    if len(sys.argv)>1:build(sys.argv[1]=="5e",sys.argv[2])
    else:
        for fam in ("5d","5e"):
            for mode in ("batch","meter","detail","attribution"):
                from common import entries
                if any(r["label"]==f"build-{fam}-{mode}" and r["success"] for r in entries()):continue
                charged(f"build-{fam}-{mode}",[sys.executable,"-B",__file__,fam,mode],45)
