"""Link the two solver versions through separate load contexts and a public-only ABI."""
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
from xml.sax.saxutils import escape
from campaign import ROOT,HERE,sha
from build import edit

PIN="131d10ae4499b56332787af61fe4a9306e65860f"
ARCHIVE="3aa49546ccf0bad704c2cfd77182a9d311d88622196cbdece9a7a1e9c51199b3"
SOLVER="ed03d9b9f6e3eefe20e4f193132fb5525d8624a89187da510bbfc6fa742afee8"

def plugin(host,tag):
    manifest=json.loads((ROOT.parent/"sts2-cli/logs/hotdraw-structures-build-03/build.json").read_bytes())
    solver=Path(manifest["solver"])
    archive=ROOT.parent/"hk0-isolated-131d10a/upstream.zip"
    if manifest["upstream"]!=PIN or sha(archive)!=ARCHIVE or sha(solver)!=SOLVER:raise ValueError("HotKernel identity")
    if tag.startswith("kernel"):
        patched=json.loads((ROOT/"logs/infra1h-hot-k2/manifest.json").read_bytes())
        solver=Path(patched["solver"])
        if patched["upstream"]!=PIN or sha(solver)!=patched["sha256"]:raise ValueError("Patched hot solver")
    tmp=host.parents[1]/"plugin"
    tmp.mkdir()
    shutil.copyfile(HERE/"HotBackend.cs",tmp/"HotBackend.cs")
    if tag.startswith("kernel"):
        for name in ("HotWorld.cs","HotActionBoundary.cs"):shutil.copyfile(HERE/name,tmp/name)
    if tag in ("kernel4","kernel5","kernel6"):
        import upgrade4
        upgrade4.plugin(tmp)
    if tag in ("kernel5","kernel6"):
        import finish5
        finish5.plugin(tmp)
        if tag=="kernel6":
            import selectors6
            selectors6.apply(tmp)
            # CORE includes the player itself in its public ally roster.
            edit(tmp/"HotActionBoundary.cs",'h.GetProperty("allies").GetArrayLength()!=0',
                '(h.GetProperty("allies").GetArrayLength()!=1 || h.GetProperty("allies")[0].GetProperty("hp").GetInt32()!=h.GetProperty("hp").GetInt32())')
    p=tmp/"adapter.csproj"
    refs="".join(f'<Reference Include="{n}" HintPath="{escape(str(path))}" Private="false"/>' for n,path in
                 (("CombatSolver",solver),("sts2",ROOT/"lib/sts2.dll"),("GodotSharp",host.parents[1]/"solver-bin/GodotSharp.dll")))
    p.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net9.0</TargetFramework>'
        '<AssemblyName>OfflineSearchHarness</AssemblyName><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
        '</PropertyGroup><ItemGroup>'+refs+'</ItemGroup></Project>')
    env=os.environ|dict(DOTNET_CLI_HOME=str(tmp/"cli"),DOTNET_NOLOGO="1")
    subprocess.run(["dotnet","build",p,"-c","Release","--source",ROOT/"logs/infra0-profile-host/feed","-p:NuGetAudit=false","--disable-build-servers","-m:1","-v:q"],env=env,check=True)
    out=host/"bin/Debug/net9.0/hot"
    out.mkdir(parents=True)
    adapter=tmp/"bin/Release/net9.0/OfflineSearchHarness.dll"
    shutil.copyfile(adapter,out/adapter.name)
    shutil.copyfile(solver,out/solver.name)
    (host.parents[1]/"hot.json").write_text(json.dumps(dict(upstream=PIN,archive=ARCHIVE,hot_solver=sha(solver),adapter=sha(adapter)),indent=2))

def install(host,tag):
    plugin(host,tag)
    for name in ("Frontier.cs","Retained.cs","Counters.cs","DrawWindows.cs"):
        shutil.copyfile(HERE/name,host/name)
    rules=json.load(gzip.open(ROOT/"experiments/m1-n1bc/catalog.json.gz"))["cards"]
    names=sorted(k for k,v in rules.items() if v.get("HookMask")=="None")
    (host/"HotCatalog.cs").write_text("namespace OfflineSearchHarness; internal static class HotCatalog {internal static readonly HashSet<string> Neutral=new(){"+",".join(map(json.dumps,names))+"};}")
    path=host/"IntegrationProbe.cs"
    edit(path,'if (command == "i1_infra1_reference_batch")','if (command == "i1_infra1h_frontier") return ReferenceFrontier(cmd);\n        if (command == "i1_infra1_reference_batch")')
    ref=host/"Reference.cs"
    edit(ref,"using CombatSolver;","using CombatSolver;\nusing Sts2Headless;")
    edit(ref,"referencePrefixes.Clear();","referencePrefixes.Clear(); ClearRetained(); hotWindows.Clear();")
    edit(ref,"edges[i].GetRawText()","JsonSerializer.Serialize(edges[i])")
    edit(ref,"var seed=start==0?source:referencePrefixes[keys[start-1]].Snapshot;",'''
        int logical=start;
        EngineCounts.Queries++; EngineCounts.LogicalEdges+=edges.Length;
        if(complete && HotReply(edges,keys,logical) is {} hotReply)return hotReply;
        int physical=edges.Length;
        while(physical>logical && !retained.ContainsKey(keys[physical-1]))physical--;
        start=physical;
        var seed=start>logical?retained[keys[start-1]].Snapshot:
            start==0?source:referencePrefixes[keys[start-1]].Snapshot;
        EngineCounts.RetainedEdges+=start-logical;
        EngineCounts.Forks++;''')
    edit(ref,"int calls = 0;","int calls=start-logical;")
    edit(ref,"var law = start==0?_law.Fork()", "var law = start>logical?retained[keys[start-1]].Law.Fork():start==0?_law.Fork()")
    edit(ref,"calls++;","calls++; EngineCounts.LegacyEdges++;")
    edit(ref,'if (probe.Boundary == "public_draw" && tape.Used==draws.Length)\n                    return new {kind="R",support=tape.Options,batch=tape.Batch,calls};','''if (probe.Boundary == "public_draw" && tape.Used==draws.Length){
                    EngineCounts.Chance++;
                    if(complete && !choice && edge.Equals(edges[^1]))RememberWindow(keys[^1],tape,before,_episodeMenu![index].Action.CardId);
                    return new {kind="R",support=tape.Options,batch=tape.Batch,calls};
                }''')
    edit(ref,"if(start<edges.Length &&", "if(logical<edges.Length &&")
    edit(ref,"referencePrefixes[oldest].Snapshot.ReleaseSimulator();","Retire(oldest);")
    f=host/"Frontier.cs"
    edit(f,"nextToken=0;","EngineCounts.Fifo++; nextToken=0;")
    edit(f,"token=++nextToken;","EngineCounts.ModelNodes++; token=++nextToken;")
    if tag.startswith("kernel"):
        for name in ("WorldAudit.cs","ActionBridge.cs","Conditional.cs"):
            shutil.copyfile(HERE/name,host/name)
        edit(path,"var response = Dispatch(sim, cmd);",
             'var response = Dispatch(sim, cmd); if (ResourceSampling.AuditWorld) OfflineSearchHarness.WorldAudit.Observe(cmd,response);')
        edit(host/"ResourceSampling.cs","    internal static readonly bool PerRequest",
             '    internal static readonly bool AuditWorld=Environment.GetEnvironmentVariable("INFRA1H_AUDIT_WORLD")=="1";\n    internal static readonly bool PerRequest')
        edit(ref,"if (choice) InteractiveView();\n                else ObserveNosl(_root, before);",
             "object? wire=null; if(choice)InteractiveView(); else wire=ObserveNosl(_root,before);")
        edit(ref,"using var tape = Observer(law, draws, true, false).Enter();",
             "if(complete && wire!=null && draws.Length==0 && edge.Equals(edges[^1]) && HotAction(wire,before,law,index,calls+1) is {} kernel)return kernel;\n                using var tape = Observer(law, draws, true, false).Enter();")
        edit(path,'if (command == "i1_infra1h_frontier")', 'if (command == "i1_infra1h_conditional") return ConditionalRun(cmd);\n        if (command == "i1_infra1h_frontier")')
    if tag in ("kernel3","kernel4","kernel5","kernel6"):
        from optimize import apply
        apply(host)

    if tag in ("kernel4","kernel5","kernel6"):
        import upgrade4
        upgrade4.host(host)
    if tag in ("kernel5","kernel6"):
        import finish5
        finish5.host(host)
