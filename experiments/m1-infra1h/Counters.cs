using System.Text.Json;

namespace Sts2Headless;

internal static class EngineCounts
{
    internal static long Queries, LogicalEdges, LegacyEdges, RetainedEdges, HotDraws, HotReplies, Imports, Rejects, Windows, Forks, Chance, Choosers, Strategic, Terminal, Fifo, ModelNodes;
    internal static readonly Dictionary<string,long> Reasons=new();
    internal static void Reason(string key)=>Reasons[key]=Reasons.GetValueOrDefault(key)+1;
    static EngineCounts()
    {
        AppDomain.CurrentDomain.ProcessExit+=(_,_)=>File.WriteAllText("infra1h-engine.json",JsonSerializer.Serialize(new{
            Queries,LogicalEdges,LegacyEdges,RetainedEdges,HotDraws,HotReplies,Imports,Rejects,Windows,Forks,
            Chance,Choosers,Strategic,Terminal,Fifo,ModelNodes,Reasons,
            gc=new[]{GC.CollectionCount(0),GC.CollectionCount(1),GC.CollectionCount(2)}}));
    }
}
