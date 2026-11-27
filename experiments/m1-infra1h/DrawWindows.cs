using System.Reflection;
using System.Runtime.Loader;
using System.Text.Json;
using CombatSolver;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Simulation;
using Sts2Headless;

namespace OfflineSearchHarness;

internal static class HotBridge
{
    private sealed class Context(string directory):AssemblyLoadContext("1H.HotKernel")
    {
        protected override Assembly? Load(AssemblyName name) =>
            name.Name=="CombatSolver" ? LoadFromAssemblyPath(Path.Combine(directory,"CombatSolver.dll")) : null;
    }
    private static readonly Type Backend;
    internal static Type Type(string name)=>Backend.Assembly.GetType(name,true)!;
    internal static readonly Func<string[],int[],int,object> Open;
    internal static readonly Func<object,string[],Dictionary<string,int>?> Branch;
    static HotBridge()
    {
        string directory=Path.Combine(AppContext.BaseDirectory,"hot");
        var asm=new Context(directory).LoadFromAssemblyPath(Path.Combine(directory,"OfflineSearchHarness.dll"));
        Backend=asm.GetType("HotBackend",true)!;
        Open=Backend.GetMethod("Open")!.CreateDelegate<Func<string[],int[],int,object>>();
        Branch=Backend.GetMethod("Branch")!.CreateDelegate<Func<object,string[],Dictionary<string,int>?>>();
    }
}
internal sealed partial class FirstWin
{
    private sealed record Window(object Parent,int Batch);
    private readonly Dictionary<string,Window> hotWindows=new();
    private static readonly HashSet<string> DrawNeutralPowers = new(StringComparer.Ordinal){
        "STRENGTH_POWER","DEXTERITY_POWER","FRAIL_POWER","WEAK_POWER","VULNERABLE_POWER","BARRICADE_POWER",
        "RITUAL_POWER","ARTIFACT_POWER","PLATING_POWER","THORNS_POWER","NO_DRAW_POWER"};
    private static readonly HashSet<string> DrawNeutralRelics = new(StringComparer.Ordinal){
        "BURNING_BLOOD","BLACK_BLOOD","LOST_COFFER","SWORD_OF_STONE","SHOVEL","STRAWBERRY",
        "GLASS_EYE","SAND_CASTLE","TOUCH_OF_OROBAS"};
    private static string EdgeKey(int action,IEnumerable<string> draws)=>
        JsonSerializer.Serialize(new{action,draws});

    // "batch" is computed by the original callback after payment, target effects,
    // hand cap and current public-law checks. Model only the uninterrupted draws.
    private void RememberWindow(string key,TurnDrawTape tape,SimulationSnapshot parent,string? cardId)
    {
        if(tape.Batch<2 || tape.Batch>10 || hotWindows.ContainsKey(key))return;
        if(cardId is not ("BATTLE_TRANCE" or "OFFERING" or "POMMEL_STRIKE" or "SHRUG_IT_OFF"))return;
        if(tape.Law.Missing!=null || tape.Law.OrderMissing!=null || tape.Law.Top.Count!=0 || tape.Law.Bottom.Count!=0)return;
        var support=tape.Options!;
        if(support.Count<2 || support.Values.Sum()>256 || support.Keys.Any(k=>!HotCatalog.Neutral.Contains(k.Split('#')[0])))return;
        var combat=(SimulatedCombatState)parent.Simulator.State.CombatState;
        if(combat.EffectivePowers().Any(p=>!DrawNeutralPowers.Contains(p.Id.Entry)) ||
           combat.RelicsOf(_player).Any(r=>!DrawNeutralRelics.Contains(r.Id.Entry)))return;
        if(hotWindows.Count>=128)hotWindows.Remove(hotWindows.Keys.First());
        var names=support.Keys.Order(StringComparer.Ordinal).ToArray();
        hotWindows[key]=new(HotBridge.Open(names,names.Select(k=>support[k]).ToArray(),tape.Batch),tape.Batch);
        EngineCounts.Windows++;
    }
    private object? HotReply(JsonElement[] edges,string[] keys,int logical)
    {
        if(hotWindows.Count==0 || edges.Length==0 || logical>=edges.Length)return null;
        var last=edges[^1];
        var draws=last.GetProperty("draws").Deserialize<string[]>()!;
        int action=last.GetProperty("action").GetInt32();
        var parent=edges.Length==1?"C":keys[^2];
        for(int i=draws.Length-1;i>=0;i--)
        {
            var baseKey=parent+"|"+EdgeKey(action,draws.Take(i));
            if(!hotWindows.TryGetValue(baseKey,out var w))continue;
            var tail=draws[i..];
            if(tail.Length>=w.Batch)continue;
            var support=HotBridge.Branch(w.Parent,tail);
            if(support==null)continue;
            EngineCounts.HotDraws+=tail.Length;
            EngineCounts.HotReplies++;
            return new{kind="R",support,batch=w.Batch-tail.Length,calls=edges.Length-logical};
        }
        return null;
    }
}
