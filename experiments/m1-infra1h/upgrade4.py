"""Last production build. Apply narrow additions after assembling the versioned parent."""
from build import edit
from campaign import HERE

def plugin(folder):
    backend=folder/"HotBackend.cs"
    edit(backend,'if(ids.Length!=1)return null; // ambiguous public instance requires full solver',
         'if(ids.Length==0)return null; // Only the type-level marginal is returned. All copies have the same public token.')
    world=folder/"HotWorld.cs"
    edit(world,'    public static string? Start', (HERE/"choices4.cs").read_text()+'\n    public static string? Start')
    edit(world,'var root=HotRootBuilder','pending=null;captured=null;\n        var root=HotRootBuilder')
    edit(world,'HotAction play;','''captured=null;
        HotChoiceSelection[] selected=[];
        HotAction play;
        if(pending is {} choice){
            if(kind=="select_candidate"){
                int idx=action.GetProperty("choice").GetInt32();
                selectedKey=VisibleKey(h.GetProperty("decision").GetProperty("candidates")[idx]);
                return choice.Options.ContainsKey(selectedKey)?null:"invalid_selected_instance";
            }
            if(kind!="confirm_selection" || selectedKey==null || !choice.Options.TryGetValue(selectedKey,out var binding))return "invalid_confirmation";
            world=choice.Parent;cold=choice.Cold;play=choice.Action;selected=[binding];pending=null;
        }
        else''')
    edit(world,'HotStepResult result;', 'var parent=world;var parentCold=cold;\n        HotStepResult result;')
    edit(world,'rules!,scratch,play);','rules!,scratch,play,selected);')
    edit(world,'if(result.NeedsChoice)return "waiting_player_selector";','if(result.NeedsChoice)return CaptureChoice(parent,parentCold,play,after);')
    edit(world,'return key;\n        }\n        var enemies', 'return key+"/"+string.Join(",",a)+"/"+string.Join(",",b);\n        }\n        var enemies')

def host(folder):
    bridge=folder/"ActionBridge.cs"
    edit(bridge,'var combat=(SimulatedCombatState)sim.State.CombatState;\n        if(combat.EffectivePowers().Any() || combat.RelicsOf(_player).Any(r=>r.Id.Entry!="BURNING_BLOOD"))return null;',
        '''// A self-targeted action ending at its first unknown draw does not depend on offensive
        // damage multipliers or end-of-turn powers. Reject every other visible listener.
        bool Guard(string reason){EngineCounts.Rejects++;EngineCounts.Reason(reason);return false;}''')
    edit(bridge,'if(h.GetProperty("decision")','''if(h.GetProperty("relics").EnumerateArray().Any(r=>r.GetString()!="BURNING_BLOOD")){Guard("public_relic");return null;}
        if(h.GetProperty("order_hooks").EnumerateArray().Any(p=>p.GetProperty("id").GetString() is not
            ("STRENGTH_POWER" or "DEXTERITY_POWER" or "FRAIL_POWER" or "WEAK_POWER" or "VULNERABLE_POWER" or
             "ARTIFACT_POWER" or "PLATING_POWER" or "RITUAL_POWER" or "THORNS_POWER" or "BARRICADE_POWER"))){Guard("public_power");return null;}
        if(h.GetProperty("decision")''')
    windows=folder/"DrawWindows.cs"
    edit(windows,'if(combat.EffectivePowers().Any(p=>!DrawNeutralPowers.Contains(p.Id.Entry))','if(combat.EffectivePowers().Any(p=>p.IsVisible && !DrawNeutralPowers.Contains(p.Id.Entry))')
    edit(windows,'hotWindows[key]=new(HotBridge.Open', '''if(Environment.GetEnvironmentVariable("INFRA1H_RELABEL")=="1" && names.Length>=3){
            var selected=new[]{names[0]};
            var reverse=names.Reverse().ToArray();
            object Open(string[] ids)=>HotBridge.Open(ids,ids.Select(k=>support[k]).ToArray(),tape.Batch);
            var first=Open(names);var second=Open(reverse);
            string Check(object root)=>JsonSerializer.Serialize(HotBridge.Branch(root,selected)?.OrderBy(x=>x.Key,StringComparer.Ordinal));
            string a=Check(first),b=Check(second);
            if(a=="null" || a!=b || a!=Check(first))throw new InvalidOperationException("Public branch instance relabel");
            EngineCounts.Reason("verified_instance_relabel");
        }
        hotWindows[key]=new(HotBridge.Open''')
    cond=folder/"Conditional.cs"
    edit(cond,'private readonly Dictionary<int,IEnumerator<Record>> cursors=[];', '''private readonly Dictionary<int,IEnumerator<Record>> cursors=[];
    private readonly HashSet<int> singleton=[];''')
    edit(cond,'cursors.Add(cursor,Outcomes(','''// Reading the base now is exactly the first read in the lazy iterator.
            // A deterministic decision has no unvisited sibling after it.
            if(Read(route).GetProperty("kind").GetString()!="R")singleton.Add(cursor);
            cursors.Add(cursor,Outcomes(''')
    edit(cond,'if(kind=="decision"){suspended=true;break;}','if(kind=="decision" && !singleton.Contains(cursor)){suspended=true;break;}')
    edit(cond,'it.Dispose();cursors.Remove(cursor);','it.Dispose();cursors.Remove(cursor);singleton.Remove(cursor);')

    import shutil
    shutil.copyfile(HERE/"SettledReplies.cs",folder/"SettledReplies.cs")
    ref=folder/"Reference.cs"
    edit(ref,"hotWindows.Clear();","hotWindows.Clear();settledReplies.Clear();")
    edit(ref,"if(complete && HotReply", "if(complete && keys.Length>0 && _selection.Count==0 && !episode.Waiting && ReadSettled(keys[^1],edges.Length-logical) is {} prior)return prior;\n        if(complete && HotReply")
    for reply in ('new {kind="C",state=tape.Strategic,calls}', 'new {kind=s.PlayerDead?"death":"victory",state=new {hp=s.PlayerHp,max_hp=s.PlayerMaxHp},calls}'):
        edit(ref,'return '+reply+';', 'return SaveSettled(keys[^1],'+reply+',complete && selected.Length==0 && !episode.Waiting && edge.Equals(edges[^1]));')
    counts=folder/"Counters.cs"
    edit(counts,"internal static long Queries","internal static long SettledHits,Queries")
    edit(counts,"Queries,LogicalEdges,LegacyEdges","SettledHits,Queries,LogicalEdges,LegacyEdges")
