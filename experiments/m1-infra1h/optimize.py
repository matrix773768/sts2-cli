from pathlib import Path
import shutil
from build import edit
from campaign import HERE

def apply(host):
    shutil.copyfile(HERE/"HostTimers.cs",host/"HostTimers.cs")
    ref=host/"Reference.cs"
    view=host/"NoslPublicEpisode.cs"
    edit(view,"bool previewMoves = true)","bool previewMoves = true, bool bindOnly = false)")
    edit(view,"var discard = pc.DiscardPile.Cards.Select((c, i) => NoslInstance(c, i)).ToArray();","var discard = bindOnly ? Array.Empty<NoslCard>() : pc.DiscardPile.Cards.Select((c, i) => NoslInstance(c, i)).ToArray();")
    edit(view,"var preview = previewMoves ?", "if(bindOnly){moves.Add(new(plan,null));continue;}\n                var preview = previewMoves ?")
    edit(view,"_episodeMenu = moves.ToArray();\n        return new","_episodeMenu = moves.ToArray();\n        if(bindOnly)return _episodeMenu;\n        return new")
    edit(ref,"var episode = (CombatBeamSolver.InteractiveCombat)_interactive!;",
        "using var totalTimer=new HostTimers.Timer(ref HostTimers.Reference);\n        var episode = (CombatBeamSolver.InteractiveCombat)_interactive!;")
    edit(ref,"var root = _pre0bSolver!.TacticalFork(seed);","SimulationSnapshot root; using(new HostTimers.Timer(ref HostTimers.Fork))root=_pre0bSolver!.TacticalFork(seed);")
    edit(ref,"object? wire=null; if(choice)InteractiveView(); else wire=ObserveNosl(_root,before);",
         "object? wire=null; using(new HostTimers.Timer(ref HostTimers.Bind)){if(choice)InteractiveView(); else ObserveNosl(_root,before,previewMoves:false,bindOnly:true);}")
    edit(ref,"if(complete && wire!=null && draws.Length==0 && edge.Equals(edges[^1]) && HotAction(wire,before,law,index,calls+1) is {} kernel)return kernel;",
         """if(complete && !choice && draws.Length==0 && edge.Equals(edges[^1]) && _episodeMenu![index].Action.CardId is ("BATTLE_TRANCE" or "SHRUG_IT_OFF" or "OFFERING")){
                    wire=ObserveNosl(_root,before);
                    if(HotAction(wire,before,law,index,calls+1) is {} kernel)return kernel;
                }""")
    edit(ref,"if (!choice) session.Play(_episodeMenu![index].Action);",
         "if (!choice) {using var playTimer=new HostTimers.Timer(ref HostTimers.LegacyStep); session.Play(_episodeMenu![index].Action);}")
    edit(ref,'if (probe.Boundary == "strategic_c") return new {kind="C",state=tape.Strategic,calls};',
         'if (probe.Boundary == "strategic_c"){EngineCounts.Strategic++;return new {kind="C",state=tape.Strategic,calls};}')
    edit(ref,'return new {kind=s.PlayerDead?"death":"victory",state=new {hp=s.PlayerHp,max_hp=s.PlayerMaxHp},calls};',
         '{EngineCounts.Terminal++; return new {kind=s.PlayerDead?"death":"victory",state=new {hp=s.PlayerHp,max_hp=s.PlayerMaxHp},calls};}')
    edit(host/"ActionBridge.cs","var act=_episodeMenu!", "using var timer=new HostTimers.Timer(ref HostTimers.HotAction); var act=_episodeMenu!")
    edit(host/"DrawWindows.cs","if(hotWindows.Count==0","using var timer=new HostTimers.Timer(ref HostTimers.HotWindow); if(hotWindows.Count==0")
    edit(host/"Frontier.cs","if(_episode==null)","using var timer=new HostTimers.Timer(ref HostTimers.Fifo); if(_episode==null)")
    edit(host/"Conditional.cs",'if(cmd.TryGetProperty("reset",out var reset)','using var timer=new HostTimers.Timer(ref HostTimers.Conditional); if(cmd.TryGetProperty("reset",out var reset)')
