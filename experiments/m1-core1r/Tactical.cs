using System.Diagnostics;
using System.Text.Json;
using CombatSolver;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Simulation;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    internal Dictionary<string,object?> Tactical(JsonElement req)
    {
        var episode=(CombatBeamSolver.InteractiveCombat)_interactive!;
        var saved=_episodeMenu;
        if (episode.Waiting) return new(){["type"]="core1r.stop.v1",["kind"]="unresolved",["reason"]="pending_choice",["calls"]=0};
        try
        {
            var result=new Tactics(this,req).Run(episode.Current);
            result.TryAdd("type","core1r.settlement.v1");
            return result;
        }
        finally { _episodeMenu=saved; }
    }

    private sealed class Tactics(FirstWin owner,JsonElement request)
    {
        private sealed record Move(NoslAction Menu,PlanAction Plan,string Role,string Token,int Strength,bool Sensitive,int EnemyIndex)
        {
            internal bool Simple => Role is "attack" or "block";
            internal int Order => Role switch { "strength"=>0,"dexterity"=>1,"vulnerable"=>2,"attack"=>3,"block"=>4,_=>5 };
        }
        private sealed record Link(object Input,int To,double? Probability=null);
        private sealed class Node(string kind)
        {
            public string Kind { get; }=kind;
            public object? State { get; set; }
            public Dictionary<string,int>? Belief { get; set; }
            public int[]? Joint { get; set; }
            public int? End { get; set; }
            public string[] Active { get; set; }=[];
            public string? Approximation { get; set; }
            public List<Link> Edges { get; }=[];
        }

        private readonly List<Node> nodes=[];
        private readonly List<CombatBeamSolver.InteractiveCombat> owners=[];
        private readonly Queue<Action> draws=[];
        private readonly Dictionary<string,int> counts=[];
        private readonly int cap=Math.Clamp(request.GetProperty("budget").GetInt32(),1,12000);
        private readonly string mode=request.GetProperty("mode").GetString()!;
        private readonly List<int[]> front=[];
        private string[] roster=[];
        private int calls;
        private bool baseline=true;
        private static readonly JsonSerializerOptions Wire=new(){PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower};
        private void Count(string name)=>counts[name]=counts.GetValueOrDefault(name)+1;
        private int Add(string kind) { nodes.Add(new(kind)); return nodes.Count-1; }
        private int Stop(string reason) { Count(reason); return Add(reason); }
        private static bool Dominates(int[] a,int[] b)=>a.Length==b.Length && a.Zip(b).All(x=>x.First>=x.Second);
        private static string[] Roster(SimulationSnapshot s)=>((SimulatedCombatState)s.Simulator.State.CombatState)
            .KnownEnemies.Select(e=>$"{e.CombatId}/{e.Monster?.Id.Entry}").ToArray();
        private static void Canonical(SimCardPile pile)
        {
            var cards=pile.Cards.OrderBy(c=>CardChoiceSupport.ChoiceCardKey(c),StringComparer.Ordinal).ToArray();
            pile.Clear();
            foreach(var c in cards) pile.Add(c);
        }
        private int[] Joint(SimulationSnapshot s)
        {
            var sim=s.Simulator;
            var combat=(SimulatedCombatState)sim.State.CombatState;
            int Power(string id)=>combat.EffectivePowers().Where(p=>p.Owner==owner._player.Creature && p.Id.Entry==id)
                .Sum(p=>p.Amount);
            return [s.PlayerHp,s.PlayerBlock,s.Energy,Power("STRENGTH_POWER"),Power("DEXTERITY_POWER"),
                Power("DEMON_FORM_POWER"),..combat.KnownEnemies.Select(e=>-Math.Max(0,sim.State.GetCreature(e).CurrentHp))];
        }
        // Equal target/cost dominance is an explicitly limited candidate heuristic.
        private static bool Stronger(Move a,Move b)=>a.Simple && !a.Sensitive && !b.Sensitive && a.Role==b.Role &&
            a.Menu.Target==b.Menu.Target && a.Menu.Cost==b.Menu.Cost && a.Menu.StarCost==b.Menu.StarCost &&
            a.Strength>b.Strength;
        private static bool Relates(Move a,Move b)=>a.Role!="special" && b.Role!="special" &&
            !(a.Role=="vulnerable" && b.Role=="vulnerable") && !a.Sensitive && !b.Sensitive;
        private static string? Precedes(Move a,Move b)
        {
            if (!Relates(a,b)) return null;
            if (a.Role=="strength" && b.Role is "attack" or "vulnerable" ||
                a.Role=="dexterity" && b.Role=="block" ||
                a.Role=="vulnerable" && b.Role=="attack" && a.Menu.Target==b.Menu.Target) return "precedence";
            if (a.Order<b.Order || a.Order==b.Order && (a.Strength>b.Strength ||
                a.Strength==b.Strength && string.CompareOrdinal(a.Token,b.Token)<0)) return "canonical";
            return null;
        }
        private (Move[],string[]) Menu(SimulationSnapshot s,Node n)
        {
            var sim=s.Simulator;
            var combat=(SimulatedCombatState)sim.State.CombatState;
            var pc=sim.State.GetPlayerCombatState(owner._player);
            Canonical(pc.DiscardPile);
            n.State=owner.ObserveNosl(owner._root,s);
            var wire=JsonSerializer.SerializeToElement(n.State,Wire);
            var menu=wire.GetProperty("actions").Deserialize<NoslAction[]>(Wire)!;
            var active=new HashSet<string>();
            bool atk=false,skill=false;
            foreach(var r in combat.RelicsOf(owner._player))
            {
                if (r.Id.Entry is "NUNCHAKU" or "TUNING_FORK")
                {
                    int counter=combat.ReadRelicCounter(sim,r)%r.DynamicVars.Cards.IntValue;
                    if (counter+1>=r.DynamicVars.Cards.IntValue)
                    {
                        active.Add(r.Id.Entry+"@"+counter);
                        if (r.Id.Entry=="NUNCHAKU") atk=true; else skill=true;
                    }
                }
                else if (r.Id.Entry!="BURNING_BLOOD") { active.Add(r.Id.Entry); atk=skill=true; }
            }
            foreach(var p in wire.GetProperty("order_hooks").EnumerateArray())
            {
                var id=p.GetProperty("id").GetString()!;
                if (id is "STRENGTH_POWER" or "DEXTERITY_POWER" or "WEAK_POWER" or "FRAIL_POWER" or "VULNERABLE_POWER")
                    continue;
                // This label and owner are exported only for a game-visible Power.
                if (p.GetProperty("owner").GetInt32()<0) skill=true;
                atk=true;
                active.Add(id);
            }
            var list=new List<Move>();
            foreach(var m in menu)
            {
                if (m.Kind=="end_turn") {n.End=m.Index; continue;}
                var plan=owner._episodeMenu![m.Index].Action;
                var card=pc.Hand.Cards[m.Card!.Value].Preview;
                string role=card.Id.Entry switch {
                    "STRIKE_IRONCLAD" or "STRIKE_SILENT"=>"attack","DEFEND_IRONCLAD" or "DEFEND_SILENT"=>"block","INFLAME" or "FLEX"=>"strength",
                    "FOOTWORK"=>"dexterity","BASH" or "TRIP"=>"vulnerable",_=>"special"};
                if (card.Enchantment!=null || card.Affliction!=null || m.Choice!=null || m.EnergyX || m.StarX) role="special";
                bool sensitive=role switch {"attack" or "vulnerable"=>atk,"special"=>true,_=>skill};
                var target=combat.KnownEnemies.ToList().FindIndex(e=>e.CombatId==plan.TargetCombatId);
                var token=$"{role}/{plan.CardStateKey}/{target}/{m.Cost}/{m.StarCost}";
                list.Add(new(m,plan,role,token,m.Preview?.DamagePerHit??m.Preview?.Block??0,sensitive,
                    m.TargetSide=="enemy"?target:-1));
                if (role is "strength" or "dexterity" or "vulnerable") active.Add(role+"-before-beneficiary");
            }
            return (list.ToArray(),active.Order().ToArray());
        }

        internal Dictionary<string,object?> Run(SimulationSnapshot initial)
        {
            var t=Stopwatch.StartNew();
            var root=owner._pre0bSolver!.TacticalFork(initial);
            try
            {
                Canonical(root.Simulator.State.GetPlayerCombatState(owner._player).DrawPile);
                var bag=request.GetProperty("bag").Deserialize<Dictionary<string,int>>();
                if(mode=="settle") return Settle(root,bag);
                roster=Roster(root);
                Visit(root,bag,[],0,[]);
                baseline=false;
                while(draws.TryDequeue(out var expand)) expand();
                return new(){["type"]="core1r.turn.v1",["mode"]=mode,["nodes"]=JsonSerializer.SerializeToElement(nodes,Wire),
                    ["no_draw_front"]=front,["counts"]=counts,["calls"]=calls,["forks"]=owners.Count+1,
                    ["milliseconds"]=t.Elapsed.TotalMilliseconds};
            }
            finally
            {
                for(int i=owners.Count-1;i>=0;i--) owners[i].Dispose();
                root.ReleaseSimulator();
            }
        }
        private static readonly HashSet<string> BeliefCards=[/* public belief catalog */];
        private static bool Qualified(Move m)=>BeliefCards.Contains(m.Plan.CardId!);

        // Execute a counterfactual A witness on forks, then resolve EndTurn. Each new draw
        // request replays from its stable action parent, including real enemy/setup effects.
        private Dictionary<string,object?> Settle(SimulationSnapshot s,Dictionary<string,int>? bag)
        {
            var route=request.GetProperty("route").EnumerateArray().ToArray();
            var initialTurn=s.Turn;
            for(int step=0;step<=route.Length;step++)
            {
                bool end=step==route.Length;
                var frame=new Node("decision");
                var (moves,_)=Menu(s,frame);
                var index=end?frame.End!.Value:route[step].GetProperty("action").GetInt32();
                var m=end?null:moves.Single(x=>x.Menu.Index==index);
                var action=end?owner._episodeMenu![index].Action:m!.Plan;
                var prefix=(end?request.GetProperty("setup"):route[step].GetProperty("draws")).Deserialize<string[]>()!;
                var session=owner._pre0bSolver!.OpenInteractiveCombat(s);
                owners.Add(session);
                var tape=new TurnDrawTape(end || Qualified(m!)?bag:null,prefix);
                using(var probe=new SearchProbe(true){TurnDraw=tape}.Enter())
                {
                    calls++;
                    try {session.Play(action);} catch(Exception) when(probe.Boundary!=null) {}
                    if(probe.Boundary!=null)
                    {
                        bool chance=end && probe.Boundary=="public_draw" && tape.Used==prefix.Length;
                        return new(){["kind"]=chance?"C":"unresolved",["reason"]=probe.Boundary,["calls"]=calls,
                            ["A"]=end?frame.State:null,["paid"]=tape.Paid,["support"]=chance?tape.Bag:null,
                            ["setup"]=end?prefix:null};
                    }
                }
                if(tape.Used!=prefix.Length) throw new ArgumentException("Unconsumed public draw transcript");
                s=session.Current;
                if(s.HasRisk || session.Waiting || s.BoundaryReason!=SearchBoundaryReason.None && s.TerminalStamp==null)
                    return new(){["kind"]="unresolved",["reason"]="pending_or_unsupported",["calls"]=calls};
                if(s.TerminalStamp!=null)
                    return new(){["kind"]=s.PlayerDead?"death":s.AllEnemiesDead?"victory":"unresolved",["calls"]=calls,
                        ["state"]=new {hp=s.PlayerHp,max_hp=s.PlayerMaxHp,gold=((SimulatedCombatState)s.Simulator.State.CombatState).GetPlayerGold(owner._player),
                            potions=owner._root.Frame.Potions}};
                bag=tape.Bag;
                if(end)
                {
                    if(s.Turn!=initialTurn+1) return new(){["kind"]="unresolved",["reason"]="not_B",["calls"]=calls};
                    var next=new Node("decision");
                    Menu(s,next);
                    return new(){["kind"]=next.End.HasValue?"B":"unresolved",["A"]=frame.State,["state"]=next.State,
                        ["belief"]=bag,["calls"]=calls};
                }
            }
            throw new InvalidOperationException("Missing EndTurn");
        }
        private int Visit(SimulationSnapshot s,Dictionary<string,int>? bag,Dictionary<string,Move> sleep,int depth,string[] observed)
        {
            if (s.HasRisk || s.BoundaryReason!=SearchBoundaryReason.None && s.TerminalStamp==null)
                return Stop("unsupported_boundary");
            bool terminal=s.TerminalStamp!=null;
            if (!terminal && !roster.SequenceEqual(Roster(s))) return Stop("unsupported_roster_change");
            int i=Add(terminal?(s.PlayerDead?"death":s.AllEnemiesDead?"victory":"unsupported_terminal"):"decision");
            var n=nodes[i];
            n.Belief=bag;
            var joint=Joint(s);
            n.Joint=joint;
            if (terminal)
                n.State=new {hp=s.PlayerHp,max_hp=s.PlayerMaxHp,gold=((SimulatedCombatState)s.Simulator.State.CombatState).GetPlayerGold(owner._player),
                    potions=owner._root.Frame.Potions};
            if (baseline && !terminal && !front.Any(f=>Dominates(f,joint)))
            {front.RemoveAll(f=>Dominates(joint,f));front.Add(joint);}
            if (terminal) return i;
            var (moves,activated)=Menu(s,n);
            n.Active=activated;
            if (observed.Length!=0)
            {
                // An optimistic one-menu estimate ranks observed draws. It is not a certified bound.
                var optimistic=(int[])joint.Clone();
                foreach(var m in moves)
                {
                    if (m.EnemyIndex>=0 && 6+m.EnemyIndex<optimistic.Length)
                        optimistic[6+m.EnemyIndex]+=m.Menu.Preview?.DamagePerHit*(m.Menu.Preview?.Hits??1)??0;
                    optimistic[1]+=m.Menu.Preview?.Block??0;
                }
                var hand=s.Simulator.State.GetPlayerCombatState(owner._player).Hand.Cards;
                bool playable=moves.Any(m=>observed.Contains(TurnDrawTape.Type(hand[m.Menu.Card!.Value])));
                bool critical=playable && (moves.Any(m=>m.Role is "strength" or "dexterity" or "vulnerable" ||
                    m.Menu.Preview==null && m.Role=="special") ||
                    !front.Any(f=>f.Length==optimistic.Length && f.Where((_,k)=>k!=2)
                        .Zip(optimistic.Where((_,k)=>k!=2)).All(x=>x.First>=x.Second)));
                n.Approximation=critical?"goal_expand":"ordinary_end_turn";
                Count(n.Approximation);
                if (!critical && mode=="reduced") return i;
            }
            if (depth>=9) {n.Approximation="depth_cap";Count("depth_cap");return i;}
            var seen=new HashSet<string>();
            foreach(var m in moves)
            {
                if(mode!="tree")
                {
                    if (!m.Sensitive && sleep.ContainsKey(m.Token)){Count("sleep_pruned");continue;}
                    if(m.Simple && !seen.Add(m.Token)){Count("duplicate_pruned");continue;}
                    if(mode!="no_dominance" && moves.Any(other=>Stronger(other,m))){Count("dominance_pruned");continue;}
                }
                var nextSleep=new Dictionary<string,Move>();
                if(mode!="tree")
                {
                    foreach(var (token,old) in sleep) if(Relates(old,m)) nextSleep[token]=old;
                    foreach(var other in moves)
                        if(Precedes(other,m) is {} reason){nextSleep[other.Token]=other;Count(reason+"_constraints");}
                }
                int to=Play(s,m,bag,nextSleep,depth,[]);
                n.Edges.Add(new(m.Menu,to));
            }
            return i;
        }
        private int Play(SimulationSnapshot parent,Move move,Dictionary<string,int>? bag,
            Dictionary<string,Move> sleep,int depth,string[] tape)
        {
            // Keep capacity for observed chance nodes. A deterministic root can use its whole budget.
            if(calls>=(baseline && draws.Count>0?Math.Max(1,cap/2):cap)) return Stop("budget");
            calls++;
            var session=owner._pre0bSolver!.OpenInteractiveCombat(parent);
            owners.Add(session);
            bool qualified=Qualified(move);
            var draw=new TurnDrawTape(qualified?bag:null,tape);
            using(var probe=new SearchProbe(true){TurnDraw=draw}.Enter())
            {
                try { session.Play(move.Plan); }
                catch(Exception) when(probe.Boundary!=null) {}
                catch(NotSupportedException) {return Stop("unsupported_action");}
                if(probe.Boundary=="public_draw")
                {
                    int c=Add("C");
                    var options=draw.Bag!.OrderBy(k=>k.Key,StringComparer.Ordinal).ToArray();
                    int total=options.Sum(k=>k.Value);
                    nodes[c].State=new {paid=draw.Paid,bag=options.ToDictionary(),events=tape};
                    void Expand()
                    {
                        foreach(var (key,count) in options)
                        {
                            int to=tape.Length>=2?Stop("draw_depth_cap"):Play(parent,move,bag,[],depth,[..tape,key]);
                            nodes[c].Edges.Add(new(key,to,(double)count/total));
                        }
                    }
                    draws.Enqueue(Expand);
                    return c;
                }
                if(probe.Boundary!=null) return Stop(probe.Boundary);
            }
            if(session.Waiting) return Stop("unsupported_pending_choice");
            // Unqualified special effects can place or generate a card in the draw pile.
            var nextBag=qualified?draw.Bag:null;
            return Visit(session.Current,nextBag,sleep,depth+1,tape);
        }
    }
}
