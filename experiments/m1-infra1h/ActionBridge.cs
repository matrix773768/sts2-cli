using System.Text.Json;
using Sts2Headless;
using CombatSolver;
using CombatSolver.Engine.InCombat.Simulation;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    private static readonly Func<JsonElement,Dictionary<string,int>,int,int,int> NextDraw =
        HotBridge.Type("HotActionBoundary").GetMethod("Next")!.CreateDelegate<Func<JsonElement,Dictionary<string,int>,int,int,int>>();

    private object? HotAction(object wire,SimulationSnapshot before,PileLaw law,int index,int calls)
    {
        var act=_episodeMenu![index].Action;
        if(act.CardId is not ("BATTLE_TRANCE" or "SHRUG_IT_OFF" or "OFFERING"))return null;
        if(law.Top.Count!=0 || law.Bottom.Count!=0 || law.Missing!=null || law.OrderMissing!=null || law.Counts.Count<2)return null;
        var sim=before.Simulator;
        var combat=(SimulatedCombatState)sim.State.CombatState;
        if(combat.EffectivePowers().Any() || combat.RelicsOf(_player).Any(r=>r.Id.Entry!="BURNING_BLOOD"))return null;
        var h=JsonSerializer.SerializeToElement(wire,Program.JsonOpts);
        if(h.GetProperty("decision").GetProperty("phase").GetString()!="combat")return null;
        if(h.GetProperty("deck").EnumerateArray().Any(c=>c.TryGetProperty("enchantment",out _) || c.TryGetProperty("affliction",out _)))return null;
        if(h.GetProperty("hand").EnumerateArray().Any(c=>!HotCatalog.Neutral.Contains(c.GetProperty("id").GetString()!)))return null;
        if(law.Counts.Values.Sum()!=h.GetProperty("draw_count").GetInt32())return null;
        var slot=h.GetProperty("actions")[index].GetProperty("card").GetInt32();
        int batch;
        try{batch=NextDraw(h,law.Counts,slot,sim.GetMaxHandSize(_player));}
        catch(Exception e){EngineCounts.Reason("public_import/"+e.GetType().Name+":"+e.GetBaseException().Message);return null;}
        if(batch<=0){EngineCounts.Reason("public_action_guard");return null;}
        EngineCounts.Imports++;
        return new{kind="R",support=law.Counts,batch,calls};
    }
}
