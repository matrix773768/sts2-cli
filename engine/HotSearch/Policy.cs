using System.Security.Cryptography;
using System.Text.Json;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;

internal sealed partial class Battle
{
    // Parent keys distinguish histories that converge to the same observation.
    private sealed class Policy
    {
        internal sealed record Edge(int Parent, string View, int Index, int Node);
        private readonly Dictionary<(int,string),Edge> nodes=new();
        public IEnumerable<Edge> Edges=>nodes.Values;
        public int Bind(int parent,string view,int index){
            if(nodes.TryGetValue((parent,view),out var found)){
                if(found.Index!=index)throw new NotSupportedException("policy/ambiguous_observation");
                return found.Node;
            }
            var edge=new Edge(parent,view,index,nodes.Count+1);
            nodes.Add((parent,view),edge);
            return edge.Node;
        }
    }
    private static string Stamp(object facts,object? prompt=null){
        // Bind the complete published menu and public features; actual and hypothetical use one encoding.
        using var sha=IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var bytes=JsonSerializer.SerializeToUtf8Bytes(new{facts,prompt});
        sha.AppendData(bytes);
        string key=Convert.ToHexString(sha.GetHashAndReset());
        if(Environment.GetEnvironmentVariable("HOTSEARCH_VIEWS") is string folder){
            string path=Path.Combine(folder,key+".json");
            if(!File.Exists(path))File.WriteAllBytes(path,bytes);
        }
        return key;
    }
    private int PickForSetup(CombatHotState s, StepEvent ev){
        // These menus add or recover the selected card. Hand-cost/exhaust prompts use the baseline order.
        if(ev.Phase is not ("GeneratedCard" or "DiscardPile" or "ExhaustPile"))return 0;
        double Score(PlayerOption option){
            if(option.Kind==HotChoiceKind.None)return 0;
            int slot=HotCombatEngine.FindCardIndexByUidAnyPile(in s,option.Instance);
            var card=option.Kind==HotChoiceKind.GeneratedCard?rules.Cards[option.Def]:rules.Cards[s.Cards[slot].CardDefId];
            byte upgrade=option.Kind==HotChoiceKind.GeneratedCard?(byte)0:s.Cards[slot].UpgradeLevel;
            return card.GetDamage(upgrade,0)+card.GetBlock(upgrade,0)+
                (card.Type.ToString()=="Power"?10:0)+(card.OrderedVarNames.Contains("Cards")?8:0)-Math.Max(0,(int)card.BaseCost);
        }
        return Enumerable.Range(0,ev.Choices.Length).OrderByDescending(i=>Score(ev.Choices[i])).First();
    }
    private HotAction Tactical(Snapshot node,string style,object facts){
        if(style=="light")return Continue(node);
        if(style=="end")return HotAction.EndTurn();
        if(style=="setup")style="build";
        var s=node.State;var actions=Menu(s,node.Cold);
        var view=JsonSerializer.SerializeToElement(facts);
        int incoming=view.GetProperty("enemies").EnumerateArray()
            .Sum(e=>e.GetProperty("attack_hits").EnumerateArray().Sum(h=>h.GetInt32()));
        int need=Math.Max(0,incoming-s.Player.Block);
        return actions.OrderByDescending(a=>{
            if(a.Kind!=HotActionKind.PlayCard)return 0;
            var c=s.Cards[a.SlotOrHandIdx];var card=rules.Cards[c.CardDefId];
            double damage=Math.Max(0,card.GetDamage(c.UpgradeLevel,c.Var0Delta))*Math.Max(1,card.GetHits(c.UpgradeLevel));
            double block=Math.Min(need,Math.Max(0,card.GetBlock(c.UpgradeLevel,c.Var1Delta)));
            double bonus=0;
            if(a.TargetEnemySlot>=0){
                var enemy=s.Enemies[a.TargetEnemySlot].Vital;
                if(damage>=enemy.CurrentHp+enemy.Block)bonus+=24;
                bonus+=1.0/(1+enemy.CurrentHp);
            }
            if(card.Type.ToString()=="Power")bonus+=style=="build"?20:4;
            if(card.OrderedVarNames.Contains("Cards") || card.OrderedVarNames.Contains("Energy"))
                bonus+=style=="build"?12:3;
            return damage+block*(style=="guard"?2.5:1.2)+bonus+.05;
        }).First();
    }
}
