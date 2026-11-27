"""Assemble independent hosts from the 1A clean sources and both frozen solver ABIs."""
import json
import os
import shutil
import subprocess
import sys
from campaign import HERE,ROOT,sha

def edit(path,old,new):
    s=path.read_text(encoding="utf-8-sig")
    if s.count(old)!=1:raise ValueError((path,old))
    path.write_text(s.replace(old,new),encoding="utf8")

def source_manifest(host):
    pdb=(host/"bin/Debug/net9.0/OfflineSearchHarness.pdb").read_bytes()
    sources={p.name:sha(p) for p in sorted(host.glob("*.cs"))}
    for name,digest in sources.items():
        if bytes.fromhex(digest) not in pdb:raise ValueError("Source absent from host PDB: "+name)
    return sources

def build(tag):
    for family in ("5d","5e"):
        original=ROOT/"logs"/f"infra1a-{family}-batch"
        dest=ROOT/"logs"/f"infra1h-{family}-{tag}"
        verified=json.loads((HERE.parent/"m1-infra1a/evidence/hosts.json").read_bytes())[original.name]
        for name,expected in verified["artifacts"].items():
            if sha(original/name)!=expected:raise ValueError(name)
        source_manifest(original/"host/Headless")
        host=dest/"host/Headless"
        host.mkdir(parents=True,exist_ok=False)
        for p in (original/"host/Headless").glob("*.cs"):shutil.copyfile(p,host/p.name)
        shutil.copytree(original/"solver-bin",dest/"solver-bin")
        project=host/"Sts2Headless.csproj"
        project.write_text((original/"host/Headless"/project.name).read_text().replace(str(original),str(dest)))
        edit(host/"IntegrationProbe.cs","var response = Dispatch(sim, cmd);\n        using var process = Process.GetCurrentProcess();",
             "var response = Dispatch(sim, cmd);\n        if (ResourceSampling.PerRequest) { using var process=Process.GetCurrentProcess(); response[\"peak_working_set_bytes\"]=process.PeakWorkingSet64; }")
        edit(host/"IntegrationProbe.cs",'        response["peak_working_set_bytes"] = process.PeakWorkingSet64;','')
        shutil.copyfile(HERE/"ResourceSampling.cs",host/"ResourceSampling.cs")
        if not tag.startswith("base"):
            from engine_build import install
            install(host,tag)
        env=os.environ|dict(DOTNET_CLI_HOME=str(dest/"cli"),NUGET_PACKAGES=str(dest/"packages"),DOTNET_CLI_TELEMETRY_OPTOUT="1",DOTNET_GENERATE_ASPNET_CERTIFICATE="false")
        feed=ROOT/"logs"/("infra0-profile-host" if family=="5d" else "infra0-world-profile")/"feed"
        subprocess.run(["dotnet","build",project,"--source",feed,"-p:NuGetAudit=false","--disable-build-servers","-m:1","-v:q"],env=env,check=True)
        artifacts={k:sha(dest/k) for k in verified["artifacts"]}
        frozen=json.loads((original/"build.json").read_bytes())
        (dest/"build.json").write_text(json.dumps(frozen|dict(artifacts=artifacts,infra1h_parent=verified["artifacts"]),indent=2))

if __name__=="__main__":build(sys.argv[1])
