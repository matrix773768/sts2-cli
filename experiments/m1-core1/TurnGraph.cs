using System.Diagnostics;
using System.Text.Json;
using CombatSolver;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;

namespace OfflineSearchHarness;

internal sealed record TurnEdge(object Input, double? Probability, int To);
internal sealed record TurnNode(string Kind, object? State, List<TurnEdge> Edges);
internal sealed record TurnCacheEntry(byte[] Bytes, HotColdSidecar? Cold, int Node);

// Cache belongs to a single root/rules contract. No capture-world path enters this graph.
internal sealed class TurnGraph(Session session, HotRules rules, int turn, int limit, bool merge)
{
    private readonly StructureTrace trace = new(session, rules);
    private readonly Dictionary<string,List<TurnCacheEntry>> buckets = [];
    public readonly List<TurnNode> Nodes = [];
    public int Attempts, Transitions, Merges, ReplayAttempts;

    private int Node(string kind, object? state = null)
    {
        Nodes.Add(new(kind,state,[]));
        return Nodes.Count - 1;
    }

    private void Edge(int source, object input, int to, double? probability = null)
        => Nodes[source].Edges.Add(new(input,probability,to));

    public int Visit(Snapshot snap, int depth)
    {
        var s = snap.State;
        var cold = snap.Cold;
        Span<byte> buffer = stackalloc byte[HotLimits.MaxPackedStateBytes];
        int size = HotStatePacker.Pack(ref s,ref cold,buffer,canonicalize:false);
        string key = depth + "/" + StructureTrace.ExactKey(snap);
        if (!buckets.TryGetValue(key,out var bucket)) buckets[key] = bucket = [];
        foreach (var other in bucket)
            if (merge && HotHash.PackedEquals(buffer[..size],cold,other.Bytes,other.Cold))
            {
                Merges++;
                return other.Node;
            }
        string kind = s.TerminalOutcome switch {
            HotCombatOutcome.Victory => "predicted_win", HotCombatOutcome.Defeat => "death",
            HotCombatOutcome.Ongoing when s.PlayerTurnNumber == turn => "decision",
            HotCombatOutcome.Ongoing when s.PlayerTurnNumber == turn+1 && s.CurrentSide == HotCombatSide.Player
                && s.PlayCount == 0 && session.Actions(snap,true).Contains(HotAction.EndTurn()) => "B",
            _ => "unsupported_phase"
        };
        int n = Node(kind, JsonSerializer.Deserialize<JsonElement>(session.PublicJson(snap)));
        bucket.Add(new(buffer[..size].ToArray(),cold,n));
        if (kind == "decision")
            foreach (var a in session.Actions(snap,true))
            {
                int dest = depth >= 12 ? Node("depth_cap") : Resolve(snap,a,Prefix.Empty,depth);
                Edge(n,trace.Bind(snap,a),dest);
            }
        return n;
    }

    private int Resolve(Snapshot parent, HotAction action, Prefix prefix, int depth)
    {
        if (Attempts >= limit) return Node("attempt_cap");
        Attempts++;
        var result = session.Advance(parent,action,prefix);
        if (result.Status == StepStatus.Completed)
        {
            Transitions++;
            var witness = trace.Record(parent,action,result);
            var verified = trace.Replay(parent,witness,Mode.Nosl,() => { ReplayAttempts++; return true; },true);
            if (verified.State == null) throw new InvalidOperationException("Witness: " + verified.Stop);
            int settlement = Node("settlement");
            Edge(settlement,new {witness.Move, witness.Events},Visit(result.Child!,depth+1));
            return settlement;
        }
        if (result.Status == StepStatus.Error) throw new InvalidOperationException(result.Point + "/" + result.Reason);
        if (result.Status == StepStatus.Unsupported) return Node("unsupported",new {result.Point,result.Reason});
        var e = result.Pending;
        if (result.Status == StepStatus.NeedsChoice)
        {
            int n = Node("choice",e.Address);
            foreach (var choice in e.Choices)
                Edge(n,choice,Resolve(parent,action,prefix.AddChoice(e,choice),depth));
            return n;
        }
        int chance = Node("chance",e.Address);
        foreach (var g in e.Options.GroupBy(o=>o.Observation))
        {
            var input = new { observation=g.Key, instances=g.Select(o=>o.Instance).ToArray() };
            Edge(chance,input,Resolve(parent,action,prefix.AddDraw(e,g.Key),depth),g.Sum(o=>o.Probability));
        }
        return chance;
    }
}

internal static partial class HotDrawHarness
{
    private static object CoreTurn(string fixture, UnattendedTestRequest request, HotRootBundle root,
        MainLoopContext loop, MegaCrit.Sts2.Core.Combat.CombatState combat)
    {
        var clock = Stopwatch.StartNew();
        var session = new Session(root.Rules);
        var ids = BindFixtureInstances(request,root);
        var state = root.RootState;
        var belief = DrawBelief.Create([],CardIds(in state,state.DrawStart,state.DrawCount).Select(id=>ids[id]),[]);
        var start = session.Open(in state,root.RootCold,belief,ids,true);
        int limit = fixture == "core1-cap" ? 3 : 3000;
        var graph = new TurnGraph(session,root.Rules,state.PlayerTurnNumber,limit,true);
        graph.Visit(start,0);

        var variant = state;
        for (int i=0;i<state.DrawCount;i++)
            variant.Cards[state.DrawStart+i] = state.Cards[state.DrawStart+state.DrawCount-1-i];
        variant.Rng[0].Counter++;
        var other = new TurnGraph(session,root.Rules,state.PlayerTurnNumber,limit,true);
        other.Visit(session.Open(in variant,root.RootCold,belief,ids,true),0);
        Check(JsonSerializer.Serialize(graph.Nodes,Json) == JsonSerializer.Serialize(other.Nodes,Json),
            "Private deck/RNG changed the conditional graph");
        var tree = new TurnGraph(session,root.Rules,state.PlayerTurnNumber,limit,false);
        tree.Visit(start,0);
        void Compare(int a,int b)
        {
            var left = graph.Nodes[a];
            var right = tree.Nodes[b];
            Check(left.Kind == right.Kind && Equals(JsonSerializer.Serialize(left.State,Json),
                JsonSerializer.Serialize(right.State,Json)) && left.Edges.Count == right.Edges.Count,
                "Unmerged public continuation differs");
            foreach (var (x,y) in left.Edges.Zip(right.Edges))
            {
                Check(x.Probability == y.Probability && JsonSerializer.Serialize(x.Input,Json) ==
                    JsonSerializer.Serialize(y.Input,Json),"Witness edge differs");
                Compare(x.To,y.To);
            }
        }
        Compare(0,0);
        object? native = null;
        if (fixture == "core1-native")
        {
            var world = session.Open(in state,root.RootCold,belief,ids,true,keepWorldOrder:true);
            native = CompareNative(session,root,world,HotAction.EndTurn(),loop,combat);
        }
        return new { schema="core1.turn.v1", measure="exact_conditional", root=0, graph.Nodes,
            graph.Attempts,graph.Transitions,graph.ReplayAttempts,graph.Merges,invariant=true,native,
            repeatedAttempts=other.Attempts,repeatedReplays=other.ReplayAttempts,unmergedAttempts=tree.Attempts,
            unmergedReplays=tree.ReplayAttempts,unmergedNodes=tree.Nodes.Count,ms=clock.Elapsed.TotalMilliseconds };
    }
}
