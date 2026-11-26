from pathlib import Path
import sys, shutil, json
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-core2"))
import build_state
from build_state import build

def extend(solver,sim,host):
    build_state.extension(solver,sim,host)
    shutil.copyfile(HERE/"Reference.cs",host/"Reference.cs")
    build.replace(host/"IntegrationProbe.cs",'        if (command == "i1_core1r2")',
                  '        if (command == "i1_core5_reference") return new(){["type"]="core5.reference.v1",["response"]=(_episode ?? throw new InvalidOperationException("Reset first")).Reference(cmd)};\n        if (command == "i1_core1r2")')
    # Settlement needs legal bindings only. Skip computing tactical roles for the fast mode.
    build.replace(host/"Tactical.cs","var (moves,_)=Menu(s,frame);",'''Move[] moves=[];
                if(mode is "settle_fast" or "settle_batch"){
                    Canonical(s.Simulator.State.GetPlayerCombatState(owner._player).DiscardPile);
                    frame.State=owner.ObserveNosl(owner._root,s,previewMoves:false);
                    frame.End=Array.FindIndex(owner._episodeMenu!,entry=>entry.Action.Kind==PlanActionKind.EndTurn);
                } else (moves,_)=Menu(s,frame);''')
    build.replace(host/"Tactical.cs","var m=end?null:moves.Single(x=>x.Menu.Index==index);","")
    build.replace(host/"Tactical.cs","var action=end?owner._episodeMenu![index].Action:m!.Plan;","var action=owner._episodeMenu![index].Action;")

    tactical=host/"Tactical.cs"
    build.replace(tactical,'if(mode.StartsWith("settle"))','if(mode=="settle_batch") return Batch(root,bag);\n                if(mode.StartsWith("settle"))')
    build.replace(tactical,'private Dictionary<string,object?> Settle(SimulationSnapshot s,PileLaw bag)',
                  (HERE/"Batch.cs.txt").read_text()+'\n        private Dictionary<string,object?> Settle(SimulationSnapshot s,PileLaw bag, JsonElement? path=null)')
    build.replace(tactical,'var route=request.GetProperty("route").EnumerateArray().ToArray();',
                  'string key=""; var route=(path??request.GetProperty("route")).EnumerateArray().ToArray();')
    build.replace(tactical,'bool end=step==route.Length;','''bool end=step==route.Length;
                if(path!=null && !end){
                    key+="|"+route[step].GetRawText();
                    if(prefixes.TryGetValue(key,out var prior)){s=prior.State;bag=prior.Law;continue;}
                }''')
    build.replace(tactical,'bag=tape.Law;','bag=tape.Law;\n                if(path!=null && !end) prefixes[key]=(s,bag);')

if __name__=="__main__":
    build.extension=extend
    out=Path(sys.argv[1]).resolve()
    build.build(out,build.ROOT/"logs/core2-state03")
    manifest=build_state.manifest(out)
    manifest["sources"]["Reference.cs"]=build.source_sha(HERE/"Reference.cs")
    (out/"build.json").write_text(json.dumps(manifest,indent=2))
