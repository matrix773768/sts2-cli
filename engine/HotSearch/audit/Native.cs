using System.Text.Json;
using Sts2Headless;

internal static class Native
{
    public static void Serve()
    {
        var sim=new RunSimulator();
        string? line;
        while((line=Console.ReadLine())!=null){
            try{
                var cmd=JsonSerializer.Deserialize<JsonElement>(line);
                var args=new Dictionary<string,object?>();
                if(cmd.TryGetProperty("args",out var fields))
                    foreach(var field in fields.EnumerateObject())
                        args[field.Name]=field.Value.ValueKind==JsonValueKind.Number?field.Value.GetInt32():field.Value.GetString();
                var result=cmd.GetProperty("cmd").GetString()=="synthetic_start"?sim.StartSyntheticCombat(cmd):
                    sim.ExecuteAction(cmd.GetProperty("action").GetString()!,args);
                if(sim.BeforeRewards!=null)result["before_rewards"]=sim.BeforeRewards;
                Console.WriteLine(JsonSerializer.Serialize(result));
            }catch(Exception e){
                Console.WriteLine(JsonSerializer.Serialize(new{type="error",message=e.Message}));
            }
        }
    }
}
