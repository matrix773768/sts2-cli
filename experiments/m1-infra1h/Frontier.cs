using System.Text.Json;
using System.Text.Json.Serialization;

namespace Sts2Headless;

// One live reference search per lane. The queue owns complete routes and
// probability mass. Python owns encoder histories addressed by integer tokens.
internal sealed class Frontier
{
    private sealed record Edge(int action, string[] draws);
    private sealed record Node(double Probability, Edge[] Route, int History);
    private sealed record Ready(Node Node, JsonElement Reply, int Token);
    private readonly Queue<Node> queue = new();
    private readonly List<object> leaves = [];
    private List<Ready> pending = [];
    private int nextToken, remaining, pastLength, calls;

    internal void Begin(int first,int past,int limit)
    {
        pending.Clear(); leaves.Clear(); queue.Clear();
        nextToken=0; calls=0; remaining=limit; pastLength=past;
        queue.Enqueue(new(1,[new(first,[])],0));
    }
    internal Dictionary<string,object?> Run(Func<JsonElement,object> reference,int[] actions)
    {
        for (;;)
        {
            int pos=0;
            foreach (var item in pending)
            {
                var node=item.Node;
                var reply=item.Reply;
                if(item.Token>0)
                {
                    if(pos>=actions.Length) throw new ArgumentException("Incomplete decision frontier");
                    queue.Enqueue(new(node.Probability,[..node.Route,new(actions[pos++],[])],item.Token));
                }
                else if(reply.GetProperty("kind").GetString()=="R")
                {
                    var support=reply.GetProperty("support").EnumerateObject().ToArray();
                    double total=0;
                    foreach(var kv in support)total+=kv.Value.GetDouble();
                    foreach(var kv in support.OrderByDescending(k=>k.Value.GetDouble()).ThenBy(k=>k.Name,StringComparer.Ordinal))
                    {
                        Edge[] route=(Edge[])node.Route.Clone();
                        var edge=route[^1];
                        route[^1]=edge with {draws=[..edge.draws,kv.Name]};
                        queue.Enqueue(new(node.Probability*kv.Value.GetDouble()/total,route,node.History));
                    }
                }
                else
                {
                    var leaf=reply.EnumerateObject().ToDictionary(k=>k.Name,k=>(object)k.Value);
                    leaf["probability"]=node.Probability;
                    leaves.Add(leaf);
                }
            }
            if(pos!=actions.Length)throw new ArgumentException("Surplus frontier actions");
            actions=[];
            pending.Clear();
            if(remaining<=0 || queue.Count==0)
            {
                foreach(var n in queue)leaves.Add(new {kind="deferred",probability=n.Probability});
                queue.Clear();
                return new(){["done"]=true,["leaves"]=leaves,["calls"]=calls};
            }
            int width=Math.Min(32,Math.Min(queue.Count,remaining));
            remaining-=width;
            var decisions=new List<object>();
            for(int i=0;i<width;i++)
            {
                var n=queue.Dequeue();
                var request=JsonSerializer.SerializeToElement(new{route=n.Route,complete=true});
                var reply=JsonSerializer.SerializeToElement(reference(request),Program.JsonOpts);
                calls+=reply.GetProperty("calls").GetInt32();
                int token=0;
                if(reply.GetProperty("kind").GetString()=="decision" && n.Route.Length+pastLength<128)
                {
                    token=++nextToken;
                    decisions.Add(new{history=n.History,token,state=reply.GetProperty("state")});
                }
                pending.Add(new(n,reply,token));
            }
            if(decisions.Count!=0)return new(){["done"]=false,["decisions"]=decisions};
        }
    }
}
internal static partial class IntegrationProbe
{
    private static Frontier? frontier;
    private static Dictionary<string,object?> ReferenceFrontier(JsonElement cmd)
    {
        if(_episode==null)throw new InvalidOperationException("No combat");
        if(cmd.TryGetProperty("first",out var first))
        {
            frontier=new Frontier();
            frontier.Begin(first.GetInt32(),cmd.GetProperty("past").GetInt32(),cmd.GetProperty("limit").GetInt32());
        }
        var result=(frontier??throw new InvalidOperationException("No frontier")).Run(
            _episode.Reference,cmd.GetProperty("actions").Deserialize<int[]>()!);
        result["type"]="infra1h.frontier.v1";
        if((bool)result["done"]!)frontier=null;
        return result;
    }
}
