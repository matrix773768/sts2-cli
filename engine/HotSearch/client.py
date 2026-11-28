"""JSON transport to the standalone engine in a disposable game profile."""
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BUILD=ROOT/os.environ.get("HOTSEARCH_BUILD","logs/hotsearch-h4")
sys.path.insert(0,str(ROOT/"python"))
import engine_client


def launch(out,dll):
    dotnet=ROOT/"logs/m0-v5/dotnet9/dotnet.exe"
    command=[str(dotnet),"--fx-version","9.0.7",str(dll)]
    env=dict(I1_RITSU=os.environ.get("I1_RITSU",str(Path.home()/"Desktop/STEAM/steamapps/workshop/content/2868840/3747602295")),
             STS2_DOTNET_VERSION="9.0.7")
    return engine_client.EngineClient(log_root=out, startup_timeout=30, command_timeout=45,
                                      command=command, extra_env=env)


class Client:
    def __init__(self,out):
        self.out=out
        self.dll=BUILD/"bin/Release/net9.0/OfflineSearchHarness.dll"
        self.engine=launch(out,self.dll)
        self.restart_before_open=False
        self.retired_cpu=0.
        self.retired_peak=0
        self.restarts=0
        self.unmetered_hosts=0

    def restart(self):
        # A rejected native initializer can leave no settled room to tear down.
        try:
            stats=self.engine.send({"op":"metrics"})["result"]
            self.retired_cpu+=stats["cpu"]
            self.retired_peak=max(self.retired_peak,stats["peak_rss"])
        except (KeyError,RuntimeError,TimeoutError,OSError):
            self.unmetered_hosts+=1
        finally:
            self.engine.close(graceful=False)
        self.engine=launch(self.out,self.dll)
        self.restart_before_open=False
        self.restarts+=1

    def call(self,op,**fields):
        if op=="open" and (self.restart_before_open or self.engine.proc.poll() is not None):
            self.restart()
        row=self.engine.send(dict(op=op,**fields))
        if not row["ok"]:
            if op=="open":
                self.restart_before_open=True
            raise RuntimeError(row["reason"]+" @ "+str(row["where"]))
        result=row["result"]
        if op=="metrics" and self.restarts:
            result.update(cpu=result["cpu"]+self.retired_cpu,peak_rss=max(result["peak_rss"],self.retired_peak),
                          restarts=self.restarts,unmetered_hosts=self.unmetered_hosts)
        return result

    def reference(self,index,limit,models,h,history,opening):
        from models import public_b,choice_b
        memory={0:models.g2.encoder.update(history,h,h["actions"][index])}
        row=self.engine.send(dict(op="search",indices=[index],limit=limit,g2=True))
        while row["type"]=="g2":
            ticket=row["ticket"]
            try:
                parent=memory[row["parent"]]
                obs=choice_b(row["facts"],row["prompt"]) if row["prompt"] else public_b(row["facts"])
                chosen=models.rank(obs,parent,opening)[0]
                memory[ticket]=models.advance(parent,obs,obs["actions"][chosen])
            except Exception:
                self.engine.send(dict(op="g2",ticket=ticket,index=-1))
                raise
            row=self.engine.send(dict(op="g2",ticket=ticket,index=chosen))
        if not row["ok"]:raise RuntimeError(row["reason"])
        return row["result"][0]

    def close(self):
        self.engine.close(graceful=False)
