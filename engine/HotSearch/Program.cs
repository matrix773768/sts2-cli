using System.Diagnostics;
using System.Reflection;
using System.Runtime.Loader;
using System.Text.Json;
using Sts2Headless;

internal static class Program
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    internal static int Score(int parent,int ticket,object facts,object? prompt,int count)
    {
        Console.WriteLine(JsonSerializer.Serialize(new{type="g2",parent,ticket,facts,prompt},Json));
        var line=Console.ReadLine()??throw new EndOfStreamException("G2 channel closed");
        var reply=JsonSerializer.Deserialize<JsonElement>(line);
        if(reply.GetProperty("ticket").GetInt32()!=ticket || reply.GetProperty("op").GetString()!="g2")
            throw new InvalidDataException("G2 reply mismatch");
        int index=reply.GetProperty("index").GetInt32();
        return (uint)index<(uint)count?index:throw new InvalidDataException("G2 action outside menu");
    }
    public static void Main()
    {
        string Required(string name) => Environment.GetEnvironmentVariable(name) ?? throw new ArgumentException(name);
        string lib = Required("STS2_LIB"), mods = Required("I1_RITSU");
        AssemblyLoadContext.Default.Resolving += (ctx, name) => {
            foreach (var dir in new[]{lib,Path.Combine(mods,"compat/0.113.0"),Path.Combine(mods,"shared"),mods}){
                var path=Path.Combine(dir,name.Name+".dll");
                if(File.Exists(path))return ctx.LoadFromAssemblyPath(path);
            }
            return null;
        };
        Console.Error.WriteLine($"[INFO] CoreCLR {Environment.Version}");
        Console.WriteLine("{\"type\":\"ready\"}");
        Serve();
    }
    [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
    private static void Serve()
    {
        RunSimulator? native=null;
        Battle? battle=null;
        bool stopped=false;
        string? line;
        while((line=Console.ReadLine())!=null){
            try{
                var cmd=JsonSerializer.Deserialize<JsonElement>(line);
                object result;
                string? op=cmd.GetProperty("op").GetString();
                if(stopped && op is not ("open" or "restore" or "metrics"))throw new InvalidOperationException("battle stopped");
                switch(op){
                    case "open":
                        battle=null;
                        if(native!=null){native.ProbeReset(abandon:true);RunSimulator.ProbeRestoreProgress();}
                        native=new RunSimulator();
                        var start=native.StartSyntheticCombat(cmd);
                        if(!Equals(start.GetValueOrDefault("decision"),"combat_play"))
                            throw new InvalidOperationException("opening/"+JsonSerializer.Serialize(start));
                        battle=new Battle(cmd.GetProperty("spec"));
                        result=battle.View();stopped=false;
                        break;
                    case "step": result=(battle??throw new InvalidOperationException("no battle")).Play(cmd.GetProperty("index").GetInt32());break;
                    case "search": result=(battle??throw new InvalidOperationException("no battle")).Search(cmd);break;
                    case "continue": result=(battle??throw new InvalidOperationException("no battle")).Continuation();break;
                    case "checkpoint": result=(battle??throw new InvalidOperationException("no battle")).Save();break;
                    case "restore": result=(battle??throw new InvalidOperationException("no battle")).Restore(cmd.TryGetProperty("world",out var seed)?seed.GetInt32():null,
                        cmd.TryGetProperty("audit_rng",out var audit)?audit.GetInt32():null);stopped=false;break;
                    case "metrics":
                        using(var proc=Process.GetCurrentProcess())
                            result=new{cpu=proc.TotalProcessorTime.TotalSeconds,peak_rss=proc.PeakWorkingSet64};
                        break;
                    default:throw new ArgumentException("unknown command");
                }
                Console.WriteLine(JsonSerializer.Serialize(new{type="hot",ok=true,result},Json));
            }catch(Exception e){
                stopped=true;
                Console.WriteLine(JsonSerializer.Serialize(new{type="hot",ok=false,reason=e.Message,where=e.TargetSite?.Name},Json));
            }
        }
    }
}
