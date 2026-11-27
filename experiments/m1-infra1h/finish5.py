"""Add target-bound deterministic HotKernel finishes and attack-draw boundaries."""
from build import edit

def plugin(folder):
    import shutil
    from campaign import HERE
    shutil.copyfile(HERE/"PublicC.cs",folder/"PublicC.cs")
    world=folder/"HotWorld.cs"
    edit(world,"public static class HotWorld","public static partial class HotWorld")
    edit(world,"captured=new{turn=", 'if(Environment.GetEnvironmentVariable("INFRA1H_C_RECEIPTS")=="1")CapturePublicC(in s,r,draw);\n        captured=new{turn=')
    edit(world,"captured=null;\n        HotChoiceSelection", "captured=null;publicC=null;\n        HotChoiceSelection")

    src=folder/"HotActionBoundary.cs"
    edit(src,"int handSlot,int maxHand","int actionIndex,int maxHand")
    edit(src,'var selected=hand[handSlot]', '''var menu=h.GetProperty("actions")[actionIndex];
        int handSlot=menu.GetProperty("card").GetInt32();
        int target=menu.TryGetProperty("target",out var enemySlot)?enemySlot.GetInt32():-1;
        var selected=hand[handSlot]''')
    edit(src,'if(selected is not ("BATTLE_TRANCE" or "SHRUG_IT_OFF" or "OFFERING"))return -1;',
         '''bool damageOnly=selected is "STRIKE_IRONCLAD" or "BASH" or "TWIN_STRIKE";
        if(!damageOnly && selected is not ("BATTLE_TRANCE" or "SHRUG_IT_OFF" or "OFFERING" or "POMMEL_STRIKE"))return -1;
        if(target>=0){
            if(h.GetProperty("order_hooks").GetArrayLength()!=0 || h.GetProperty("allies").GetArrayLength()!=0)return -1;
            var foe=h.GetProperty("enemies")[target];
            if(!menu.TryGetProperty("preview",out var preview) || !preview.TryGetProperty("damage_per_hit",out var damage))return -1;
            int health=foe.GetProperty("hp").GetInt32()+foe.GetProperty("block").GetInt32();
            int expected=damage.GetInt32()*preview.GetProperty("hits").GetInt32();
            if(damageOnly && (health>expected || h.GetProperty("enemies").GetArrayLength()!=1 ||
                h.GetProperty("relics").GetArrayLength()!=0))return -1;
            if(!damageOnly && health<=expected)return -1;
        }''')
    edit(src,'try{HotCombatEngine.Step(ref s,ref cold,rule,new HotExecScratch(),HotAction.PlayCard(handSlot));}',
         '''try{
            var step=HotCombatEngine.Step(ref s,ref cold,rule,new HotExecScratch(),HotAction.PlayCard(handSlot,target));
            // Locked terminal utility reads exactly hp/max_hp. Reject any terminal
            // with an additional resource change or a pending player selection.
            if(damageOnly && step.Executed && !step.NeedsChoice && s.TerminalOutcome==HotCombatOutcome.Victory &&
                s.Player.CurrentHp==h.GetProperty("hp").GetInt32() && s.Player.MaxHp==h.GetProperty("max_hp").GetInt32())return -2;
        }''')

def host(folder):
    audit=folder/"WorldAudit.cs"
    edit(audit,"    private static JsonElement previous;",'''    private static readonly Func<JsonElement> ExportC=HotBridge.Type("HotWorld").GetMethod("ExportC")!.CreateDelegate<Func<JsonElement>>();
    private static readonly bool Export=Environment.GetEnvironmentVariable("INFRA1H_C_RECEIPTS")=="1";
    private static JsonElement previous;''')
    edit(audit,'if(c!=null)Record("pre_draw_C",c);','''if(c!=null)Record("pre_draw_C",c);
                if(Export && c!=null && current.TryGetProperty("observed_c",out var core))
                    File.AppendAllText("infra1h-c.jsonl",JsonSerializer.Serialize(new{root,steps,core,hot=ExportC()})+"\\n");''')
    ref=folder/"Reference.cs"
    bridge=folder/"ActionBridge.cs"
    edit(ref,'_episodeMenu![index].Action.CardId is ("BATTLE_TRANCE" or "SHRUG_IT_OFF" or "OFFERING")',
         'EligibleHotPlay(_episodeMenu![index].Action.CardId,before)')
    edit(bridge,"    private object? HotAction(",'''    private static bool EligibleHotPlay(string? id,SimulationSnapshot snapshot){
        if(id is "BATTLE_TRANCE" or "SHRUG_IT_OFF" or "OFFERING" or "POMMEL_STRIKE")return true;
        if(id is not ("STRIKE_IRONCLAD" or "BASH" or "TWIN_STRIKE"))return false;
        var sim=snapshot.Simulator;
        var combat=(SimulatedCombatState)sim.State.CombatState;
        var alive=combat.KnownEnemies.Where(e=>sim.State.GetCreature(e).IsAlive).Take(2).ToArray();
        if(alive.Length!=1)return false;
        var foe=sim.State.GetCreature(alive[0]);
        return foe.CurrentHp+foe.Block<=16;
    }
    private object? HotAction(''')
    edit(bridge,'if(act.CardId is not ("BATTLE_TRANCE" or "SHRUG_IT_OFF" or "OFFERING"))return null;',
         'bool damageOnly=act.CardId is "STRIKE_IRONCLAD" or "BASH" or "TWIN_STRIKE";')
    edit(bridge,'|| law.Counts.Count<2','|| (!damageOnly && law.Counts.Count<2)')
    edit(bridge,'var slot=h.GetProperty("actions")[index].GetProperty("card").GetInt32();','')
    edit(bridge,'NextDraw(h,law.Counts,slot,','NextDraw(h,law.Counts,index,')
    edit(bridge,'if(batch<=0)', '''if(batch==-2 && damageOnly){EngineCounts.HotFinishes++;return new{kind="victory",state=new{hp=h.GetProperty("hp"),max_hp=h.GetProperty("max_hp")},calls};}
        if(batch<=0 || damageOnly)''')
    edit(bridge,'EngineCounts.Imports++;','EngineCounts.Imports++;if(act.CardId=="POMMEL_STRIKE")EngineCounts.TargetDraws++;')
    counts=folder/"Counters.cs"
    edit(counts,'internal static long SettledHits','internal static long HotFinishes,TargetDraws,SettledHits')
    edit(counts,'SettledHits,Queries,LogicalEdges,LegacyEdges','HotFinishes,TargetDraws,SettledHits,Queries,LogicalEdges,LegacyEdges')
    # Only an already-observed, ordered repeated draw callback may open a window.
    edit(folder/"DrawWindows.cs",'"OFFERING" or "POMMEL_STRIKE" or "SHRUG_IT_OFF"',
        '"OFFERING" or "POMMEL_STRIKE" or "SHRUG_IT_OFF" or "BURNING_PACT" or "EVIL_EYE" or "EXPECT_A_FIGHT"')
