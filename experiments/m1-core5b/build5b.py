from pathlib import Path
import sys,json
B=Path(__file__).resolve().parent
sys.path.insert(0,str(B.parent/"m1-core5a"))
import build_host
from build_host import build,build_state
def extend(solver,sim,host):
    build_host.extend(solver,sim,host)
    replace=build.replace
    tape=sim/"PublicDraw.cs"
    replace(tape,"internal int Used;",(B/"PublicChoice.cs.txt").read_text()+"\n    internal int Used;")
    p=host/"Reference.cs"
    replace(p,"    // Fork",'''    private readonly Dictionary<string,(SimulationSnapshot Snapshot,PileLaw Law)> referencePrefixes=new();
    private SimulationSnapshot? referenceSource;
    private void ClearReference(){
        foreach(var item in referencePrefixes.Values)item.Snapshot.ReleaseSimulator();
        referencePrefixes.Clear();
        referenceSource=null;
    }
    // Fork''')
    replace(p,"var root = _pre0bSolver!.TacticalFork(source);",'''if(request.TryGetProperty("clear",out _)){ClearReference();return new {kind="cleared"};}
        if(!ReferenceEquals(referenceSource,source)){ClearReference();referenceSource=source;}
        var edges=request.GetProperty("route").EnumerateArray().ToArray();
        var keys=new string[edges.Length];string key="";
        for(int i=0;i<edges.Length;i++)keys[i]=key+="|"+edges[i].GetRawText();
        int start=edges.Length;
        while(start>0 && !referencePrefixes.ContainsKey(keys[start-1]))start--;
        var seed=start==0?source:referencePrefixes[keys[start-1]].Snapshot;
        var root = _pre0bSolver!.TacticalFork(seed);''')
    replace(p,"var law = _law.Fork();","var law = start==0?_law.Fork():referencePrefixes[keys[start-1]].Law.Fork();")
    replace(p,'foreach (var edge in request.GetProperty("route").EnumerateArray())','foreach (var edge in edges.Skip(start))')
    replace(p,"using var probe =", "tape.ReferenceEvents=true;\n                using var probe =")
    replace(p,'if (probe.Boundary == "strategic_c")','if(probe.Boundary=="reference_event")return new {kind="R",support=tape.Branch,calls};\n                if (probe.Boundary == "strategic_c")')
    replace(p,'var current=session.Current;', '''var current=session.Current;
            if(start<edges.Length && !session.Waiting && KnowledgeChoice(current)==null)
                referencePrefixes[keys[^1]]=(_pre0bSolver.TacticalFork(current),law.Fork());''')
    replace(sim/"CombatPredictionSimulator.Attack.cs","return Rng.CombatTargets.NextItem(validTargets);",
            'return TurnDrawTape.Current is {ReferenceEvents:true} t?t.Uniform(validTargets,"target"):Rng.CombatTargets.NextItem(validTargets);')
    replace(sim/"CombatPredictionSimulator.AutoPlay.cs","target ??= Rng.CombatTargets.NextItem(State.HittableEnemies);",
            'target ??= TurnDrawTape.Current is {ReferenceEvents:true} t?t.Uniform(State.HittableEnemies,"autoTarget"):Rng.CombatTargets.NextItem(State.HittableEnemies);')
    replace(sim/"CombatPredictionSimulator.AutoPlayContinuation.cs",'if (!state.DrawPile.IsEmpty) SearchProbe.Stop("autoplay_from_draw");',
            '''if (!state.DrawPile.IsEmpty){
                if(TurnDrawTape.Current is {ReferenceEvents:true} t && position==CardPilePosition.Top && !upgrade)
                    t.Draw(this,player,1);
                else SearchProbe.Stop("autoplay_from_draw");
            }''')
    mirrors=solver/"src/Engine/InCombat/Mirrors/Cards/OnPlay/CardSelectionCardMirrors.cs"
    replace(mirrors,"return context.Rng.CombatCardSelection.NextItem(candidates);",
            'return TurnDrawTape.Current is {ReferenceEvents:true} t?t.Uniform(candidates,"hand"):context.Rng.CombatCardSelection.NextItem(candidates);')
    replace(solver/"src/Prediction/MonsterRandomBranchResolver.cs",'if(observer?.ModelEnemy==true',
            '''if(observer is {ReferenceEvents:true} && legal.Length>1)
                return observer.Choose(legal.GroupBy(x=>"move:"+x.State.stateId).ToDictionary(g=>g.Key,g=>g.Sum(x=>(double)x.Weight))).Substring(5);
            if(observer?.ModelEnemy==true''')
if __name__=="__main__":
    out=Path(sys.argv[1]).resolve()
    build.extension=extend;build.build(out)
    (out/"build.json").write_text(json.dumps(build_state.manifest(out),indent=2))
