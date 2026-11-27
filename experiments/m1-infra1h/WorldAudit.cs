using System.Text.Json;
using Sts2Headless;

namespace OfflineSearchHarness;

internal static class WorldAudit
{
    private static readonly Func<JsonElement,string?> Start=HotBridge.Type("HotWorld").GetMethod("Start")!.CreateDelegate<Func<JsonElement,string?>>();
    private static readonly Func<JsonElement,int,JsonElement,string?> Step=HotBridge.Type("HotWorld").GetMethod("Step")!.CreateDelegate<Func<JsonElement,int,JsonElement,string?>>();
    private static readonly Func<JsonElement,string?> CheckC=HotBridge.Type("HotWorld").GetMethod("CheckC")!.CreateDelegate<Func<JsonElement,string?>>();
    private static JsonElement previous;
    private static bool active;
    private static int root=-1,steps;
    private static void Record(string stage,string? detail)
    {
        File.AppendAllText("infra1h-private.jsonl",JsonSerializer.Serialize(new{root,steps,stage,detail})+"\n");
    }
    internal static void Observe(JsonElement cmd,Dictionary<string,object?> response)
    {
        string? name=cmd.GetProperty("cmd").GetString();
        if(name=="i1_core5_reference" && cmd.TryGetProperty("diagnostic_world",out _)){active=false;return;}
        if(name is not ("i1_n2_step" or "i1_n2_reset") || !response.TryGetValue("episode",out var state))return;
        if(name=="i1_n2_step" && !active)return;
        try
        {
            var current=JsonSerializer.SerializeToElement(state,Program.JsonOpts);
            if(name=="i1_n2_reset")
            {
                root++;steps=0;
                string? reason=Start(current);
                active=reason==null;Record("import",reason);
            }
            else
            {
                string? diff=Step(previous,cmd.GetProperty("index").GetInt32(),current);
                steps++;
                string? c=CheckC(current);
                if(c!=null)Record("pre_draw_C",c);
                if(diff!=null){active=false;Record("stop",diff);}
                else if(current.GetProperty("status").GetString()!="active"){active=false;Record("terminal",current.GetProperty("status").GetString());}
            }
            previous=current;
        }
        catch(Exception ex){active=false;Record("error",ex.GetType().Name+":"+ex.GetBaseException().Message);}
    }
}
