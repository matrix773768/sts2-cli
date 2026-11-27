using System.Numerics;
using System.Text.Json;
using OfflineSearchHarness;

namespace Sts2Headless;

// Each iterator suspends on the first decision, before looking up any subsequent
// sibling. The host can drain a sequence of chance or terminal leaves locally.
internal sealed class Conditional(Func<JsonElement,object> reference)
{
    private sealed record Edge(int action,string[] draws);
    private sealed record Route(int Id,Route? Parent,Edge? Edge);
    private sealed record Record(Route Route,double Weight,bool Merged,JsonElement Reply);
    private readonly Route root=new(0,null,null);
    private readonly Dictionary<(int,int,string),Route> children=new();
    private readonly Dictionary<int,Route> routes=[];
    private readonly Dictionary<int,JsonElement> cache=[];
    private readonly Dictionary<int,IEnumerator<Record>> cursors=[];
    private readonly HashSet<int> sent=[];
    private int cap,next,cursorId,calls,merges;

    private Route Child(Route parent,int action,string[] draws)
    {
        var key=(parent.Id,action,JsonSerializer.Serialize(draws));
        if(children.TryGetValue(key,out var route))return route;
        route=new(++next,parent,new(action,draws));
        routes.Add(route.Id,route);children.Add(key,route);return route;
    }
    private static readonly JsonElement Budget=JsonSerializer.SerializeToElement(new{kind="budget"});
    private JsonElement Read(Route route)
    {
        if(cache.TryGetValue(route.Id,out var already))return already;
        if(cache.Count>=cap)return Budget;
        var path=new Stack<Edge>();
        for(var node=route;node.Edge!=null;node=node.Parent!)path.Push(node.Edge);
        var result=JsonSerializer.SerializeToElement(reference(JsonSerializer.SerializeToElement(new{route=path,complete=true})),Program.JsonOpts);
        calls+=result.GetProperty("calls").GetInt32();
        cache.Add(route.Id,result);
        return result;
    }
    private static BigInteger Choose(int n,int k)
    {
        BigInteger result=1;
        for(int i=1;i<=k;i++)result=result*(n-i+1)/i;
        return result;
    }
    private static IEnumerable<(string[],double)> Events(JsonProperty[] support,int n)
    {
        // Keep sorted token order for ties, exactly as CORE events().
        var keys=support.OrderBy(p=>p.Name,StringComparer.Ordinal).ToArray();
        if(n==1)
        {
            double total=support.Sum(x=>x.Value.GetDouble());
            foreach(var k in keys.OrderByDescending(x=>x.Value.GetDouble()))yield return ([k.Name],k.Value.GetDouble()/total);
            yield break;
        }
        var counts=keys.Select(k=>k.Value.GetInt32()).ToArray();
        int totalCount=counts.Sum();
        var denom=Choose(totalCount,n);
        IEnumerable<(string[],double)> Enumerate(int i,int required,int capacity,List<int> prefix,BigInteger ways)
        {
            if(required==0)
            {
                var left=(int[])counts.Clone();int kinds=left.Length;
                var tape=new List<string>();
                foreach(int k in prefix){if(kinds>1)tape.Add(keys[k].Name);if(--left[k]==0)kinds--;}
                yield return (tape.ToArray(),(double)ways/(double)denom);yield break;
            }
            if(i==keys.Length || capacity<required)yield break;
            capacity-=counts[i];
            for(int take=Math.Min(required,counts[i]);take>=Math.Max(0,required-capacity);take--)
            {
                for(int j=0;j<take;j++)prefix.Add(i);
                foreach(var entry in Enumerate(i+1,required-take,capacity,prefix,ways*Choose(counts[i],take)))yield return entry;
                prefix.RemoveRange(prefix.Count-take,take);
            }
        }
        foreach(var entry in Enumerate(0,n,totalCount,[],BigInteger.One))yield return entry;
    }
    private IEnumerable<Record> Outcomes(Route route,bool group,bool merged,double p)
    {
        var raw=Read(route);
        if(raw.GetProperty("kind").GetString()!="R"){yield return new(route,p,merged,raw);yield break;}
        var support=raw.GetProperty("support").EnumerateObject().ToArray();
        int n=group && support.All(x=>HotCatalog.Neutral.Contains(x.Name.Split('#')[0])) &&
            raw.TryGetProperty("batch",out var b)?b.GetInt32():1;
        if(n>1)merges++;
        double left=1;
        foreach(var (tape,w) in Events(support,n))
        {
            var edge=route.Edge!;
            var child=Child(route.Parent!,edge.action,[..edge.draws,..tape]);
            if(cache.Count>=cap && !cache.ContainsKey(child.Id))
            {yield return new(route,p*left,merged,Budget);yield break;}
            foreach(var record in Outcomes(child,group,merged||n>1,p*w))yield return record;
            left-=w;
        }
        if(Math.Abs(left)>1e-9)throw new InvalidOperationException("Invalid conditional mass");
    }
    internal Dictionary<string,object?> Run(JsonElement cmd)
    {
        int cursor,baseId=0;
        if(cmd.TryGetProperty("cursor",out var existing))cursor=existing.GetInt32();
        else
        {
            cap=cmd.GetProperty("cap").GetInt32();
            int parent=cmd.GetProperty("parent").GetInt32();
            var route=Child(parent==0?root:routes[parent],cmd.GetProperty("action").GetInt32(),[]);
            baseId=route.Id;
            cursor=++cursorId;
            cursors.Add(cursor,Outcomes(route,cmd.GetProperty("group").GetBoolean(),cmd.GetProperty("merged").GetBoolean(),cmd.GetProperty("p").GetDouble()).GetEnumerator());
        }
        var it=cursors[cursor];var items=new List<object>();
        bool suspended=false;
        while(it.MoveNext())
        {
            var r=it.Current;string kind=r.Reply.GetProperty("kind").GetString()!;
            int id=kind=="budget"?-1:r.Route.Id;
            bool transmit=id>=0 && sent.Add(id);
            items.Add(new {id,kind,p=r.Weight,merged=r.Merged,raw=transmit?(JsonElement?)r.Reply:null});
            if(kind=="decision"){suspended=true;break;}
        }
        if(!suspended){it.Dispose();cursors.Remove(cursor);}
        return new(){["type"]="infra1h.conditional.v1",["base_id"]=baseId,["cursor"]=suspended?cursor:0,
            ["rows"]=items,["size"]=cache.Count,["calls"]=calls,["merges"]=merges};
    }
}
internal static partial class IntegrationProbe
{
    private static Conditional? condition;
    private static Dictionary<string,object?> ConditionalRun(JsonElement cmd)
    {
        if(cmd.TryGetProperty("reset",out var reset)&&reset.GetBoolean())
            condition=new((_episode??throw new InvalidOperationException("Reset first")).Reference);
        return (condition??throw new InvalidOperationException("No conditional search")).Run(cmd);
    }
}
