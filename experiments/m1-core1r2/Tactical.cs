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
        if (episode.Waiting) return new(){["type"]="core1r2.stop.v1",["kind"]="unresolved",["reason"]="pending_choice",["calls"]=0};
        try
        {
            var result=new Tactics(this,req).Run(episode.Current);
            result.TryAdd("type","core1r2.settlement.v1");
            return result;
        }
        finally { _episodeMenu=saved; }
    }

    private sealed class Tactics(FirstWin owner,JsonElement request)
    {
        private sealed record Move(NoslAction Menu,PlanAction Plan,string Role,string Token,int Strength,bool Sensitive,int EnemyIndex,int Hits,int Block,int Damage,bool Draw,bool Pure,int Proc)
        {
            internal bool Simple => Role is "attack" or "block";
            internal int Order => Role switch { "engine"=>0,"energy"=>1,"strength"=>2,"dexterity"=>3,"vulnerable"=>4,"block"=>5,"attack"=>6,"mixed"=>7,"finisher"=>8,_=>9 };
        }
        private sealed record Link(object Input,int To,double? Probability=null);
        private sealed class Node(string kind)
        {
            public string Kind { get; }=kind;
            public int AtCall {get;set;}
            public object? State { get; set; }
            public object? Belief { get; set; }
            public int[]? Joint { get; set; }
            public int? End { get; set; }
            public object? Effects {get;set;}
            public string[] Active { get; set; }=[];
            public string? Approximation { get; set; }
            public List<Link> Edges { get; }=[];
        }

        private static readonly Dictionary<string,string[]> Operations=new(){/* compiled public operations */};
        private readonly List<Node> nodes=[];
        private readonly List<CombatBeamSolver.InteractiveCombat> owners=[];
        private readonly Queue<Action> draws=[],decisions=[];
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
        private static bool Stronger(Move a,Move b)=>a.Simple && a.Pure && b.Pure && a.Hits==b.Hits && !a.Sensitive && !b.Sensitive && a.Role==b.Role &&
            a.Menu.Target==b.Menu.Target && a.Menu.Cost==b.Menu.Cost && a.Menu.StarCost==b.Menu.StarCost &&
            a.Strength>b.Strength;
        private static bool Relates(Move a,Move b)=>a.Role!="special" && b.Role!="special" &&
            !(a.Role=="finisher" && (b.Menu.Cost>0 || b.Role=="energy") || b.Role=="finisher" && (a.Menu.Cost>0 || a.Role=="energy")) &&
            !(a.Proc==1 && b.Role=="energy" || b.Proc==1 && a.Role=="energy") &&
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
            bool atk=false,skill=false,playerTender=false;
            var reactiveTargets=new HashSet<int>();
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
                else if (r.Id.Entry!="BURNING_BLOOD") active.Add("default_relic:"+r.Id.Entry);
            }
            foreach(var p in wire.GetProperty("order_hooks").EnumerateArray())
            {
                var id=p.GetProperty("id").GetString()!;
                if (id is "STRENGTH_POWER" or "DEXTERITY_POWER" or "WEAK_POWER" or "FRAIL_POWER" or "VULNERABLE_POWER")
                    continue;
                // This label and owner are exported only for a game-visible Power.
                int slot=p.GetProperty("owner").GetInt32();
                if(slot<0 && id=="TENDER_POWER") playerTender=true;
                if(slot>=0 && id is "CURL_UP_POWER" or "THORNS_POWER" or "SKITTISH_POWER" or "ASLEEP_POWER" or "SLUMBER_POWER" or "TENDER_POWER") reactiveTargets.Add(slot);
                active.Add(id);
            }
            var list=new List<Move>();
            foreach(var m in menu)
            {
                if (m.Kind=="end_turn") {n.End=m.Index; continue;}
                var plan=owner._episodeMenu![m.Index].Action;
                var card=pc.Hand.Cards[m.Card!.Value].Preview;
                var vars=card.DynamicVars.Values.ToDictionary(v=>v.Name,v=>(int)v.BaseValue);
                string id=card.Id.Entry;
                var ops=Operations.GetValueOrDefault(id)??[];
                int hits=m.Preview?.Hits??Math.Max(1,vars.GetValueOrDefault("HitCount"));
                int damage=(m.Preview?.DamagePerHit??vars.GetValueOrDefault("Damage"))*hits;
                int block=m.Preview?.Block??vars.GetValueOrDefault("Block");
                bool draw=ops.Contains("Draw") || (m.Preview?.Draw??0)>0 || id is "BATTLE_TRANCE" or "FINESSE" or "FLASH_OF_STEEL" or "OFFERING";
                string role=id switch {
                    "BLOODLETTING"=>"energy","INFLAME" or "FLEX"=>"strength","FOOTWORK"=>"dexterity",
                    "TRIP" or "BASH" or "THUNDERCLAP" or "UPPERCUT"=>"vulnerable",
                    "RUPTURE" or "RAGE" or "DARK_EMBRACE"=>"engine","WHIRLWIND"=>"finisher",
                    "HEADBUTT" or "TRUE_GRIT" or "SWORD_BOOMERANG" or "HAVOC" or "ARMAMENTS" or "SECOND_WIND"
                    or "STOKE" or "BURNING_PACT" or "FIEND_FIRE" or "OFFERING"=>"special",
                    _ when ops.Contains("ApplyPowerSelf") && damage>0=>"engine",
                    _ when ops.Contains("ApplyPowerTarget")=>"special",
                    _ when ops.Contains("ApplyPowerSelf")=>"engine",
                    _ when damage>0 && block>0=>"mixed",_ when damage>0=>"attack",_ when block>0=>"block",_=>"special"};
                if(draw || card.Enchantment!=null || card.Affliction!=null || m.Choice!=null || m.StarX
                    || m.EnergyX && id!="WHIRLWIND") role="special";
                bool attack=card.Type.ToString()=="Attack";
                bool tender=playerTender && (damage>0 || block>0);
                int proc=attack && atk?1:card.Type.ToString()=="Skill" && skill?2:0;
                bool sensitive=tender || role=="special" || attack && (m.Target is int slot && reactiveTargets.Contains(slot) ||
                    m.TargetType=="AllEnemies" && reactiveTargets.Count>0) || id=="BODY_SLAM" && active.Contains("RAGE_POWER");
                var target=combat.KnownEnemies.ToList().FindIndex(e=>e.CombatId==plan.TargetCombatId);
                var token=$"{role}/{plan.CardStateKey}/{target}/{m.Cost}/{m.StarCost}";
                bool pure=role is "attack" or "block" && (ops.Length==1 && ops[0] is "Attack" or "GainBlock" || id is "STRIKE_SILENT" or "DEFEND_SILENT")
                    && id is not ("RAMPAGE" or "BODY_SLAM" or "UNMOVABLE" or "FLAME_BARRIER");
                list.Add(new(m,plan,role,token,role=="block"?block:damage,sensitive,
                    m.TargetSide=="enemy"?target:-1,hits,block,damage,draw,pure,proc));
                Count(ops.Length!=0?"catalog_operations":"dynamic_default");
                Count(role=="special"?"generated_barrier":"generated_classified");
                if (role is "strength" or "dexterity" or "vulnerable") active.Add(role+"-before-beneficiary");
            }
            n.Effects=list.Select(m=>new {index=m.Menu.Index,role=m.Role,card=m.Plan.CardId,scope=m.EnemyIndex,
                source=Operations.ContainsKey(m.Plan.CardId!)?"catalog_and_dynamic":"dynamic_and_exceptions",
                pure=m.Pure,local_conflict=m.Sensitive,threshold=m.Proc,hits=m.Hits,damage=m.Damage,block=m.Block,draw=m.Draw}).ToArray();
            return (list.ToArray(),active.Order().ToArray());
        }

        internal Dictionary<string,object?> Run(SimulationSnapshot initial)
        {
            var t=Stopwatch.StartNew();
            var root=owner._pre0bSolver!.TacticalFork(initial);
            try
            {
                Canonical(root.Simulator.State.GetPlayerCombatState(owner._player).DrawPile);
                var bag=owner._law.Fork();
                bag.Check(root.Simulator.State.GetPlayerCombatState(owner._player).DrawPile.Cards.Count);
                if(mode=="pile_fixture") return owner.PileFixture(root,bag);
                if(mode.StartsWith("settle")) return Settle(root,bag);
                roster=Roster(root);
                Visit(root,bag,[],0,[]);
                void Drain(){while(decisions.TryDequeue(out var next))next();}
                Drain();baseline=false;
                while(draws.Count>0)
                {
                    int layer=draws.Count;
                    for(int i=0;i<layer;i++)draws.Dequeue()();
                    Drain();
                }
                return new(){["type"]="core1r2.turn.v1",["mode"]=mode,["nodes"]=JsonSerializer.SerializeToElement(nodes,Wire),
                    ["no_draw_front"]=front,["counts"]=counts,["calls"]=calls,["forks"]=owners.Count+1,
                    ["milliseconds"]=t.Elapsed.TotalMilliseconds};
            }
            finally
            {
                for(int i=owners.Count-1;i>=0;i--) owners[i].Dispose();
                root.ReleaseSimulator();
            }
        }


        // Execute a counterfactual A witness on forks, then resolve EndTurn. Each new draw
        // request replays from its stable action parent, including real enemy/setup effects.
        private Dictionary<string,object?> Settle(SimulationSnapshot s,PileLaw bag)
        {
            var route=request.GetProperty("route").EnumerateArray().ToArray();
            var initialTurn=s.Turn;
            var choices=new List<string>();
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
                using var tape=owner.Observer(bag,prefix,end && mode!="settle_b",end && mode=="settle_model").Enter();
                using(var probe=new SearchProbe(true){TurnDraw=tape}.Enter())
                {
                    calls++;
                    try
                    {
                        session.Play(action);
                        if(end && owner.KnowledgeChoice(session.Current) is {} menu && menu.OptionIds.Count>0)
                        {
                            choices.Add(menu.OptionIds[0]);
                            calls++;
                            owner.SubmitKnowledgeChoice(menu,0,session);
                        }
                    }
                    catch(Exception) when(probe.Boundary!=null) {}
                    if(probe.Boundary!=null)
                    {
                        if(probe.Boundary=="strategic_c") return new(){["kind"]="C",["state"]=tape.Strategic,["choices"]=choices,["calls"]=calls,["A"]=frame.State,["approximate"]=tape.EnemyModels.Count>0};
                        bool chance=end && probe.Boundary=="public_draw" && tape.Used==prefix.Length;
                        return new(){["kind"]=chance?"R":"unresolved",["reason"]=probe.Boundary,["calls"]=calls,
                            ["A"]=end?frame.State:null,["paid"]=tape.Paid,["support"]=chance?tape.Options:null,
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
                bag=tape.Law;
                if(end)
                {
                    if(s.Turn!=initialTurn+1) return new(){["kind"]="unresolved",["reason"]="not_B",["calls"]=calls};
                    var next=new Node("decision");
                    Menu(s,next);
                    return new(){["kind"]=next.End.HasValue?"B":"unresolved",["A"]=frame.State,["state"]=next.State,
                        ["belief"]=bag.Export(),["calls"]=calls};
                }
            }
            throw new InvalidOperationException("Missing EndTurn");
        }
        private int Visit(SimulationSnapshot s,PileLaw bag,Dictionary<string,Move> sleep,int depth,string[] observed,bool cheap=false)
        {
            if (s.HasRisk || s.BoundaryReason!=SearchBoundaryReason.None && s.TerminalStamp==null)
                return Stop("unsupported_boundary");
            bool terminal=s.TerminalStamp!=null;
            if (!terminal && !roster.SequenceEqual(Roster(s))) return Stop("unsupported_roster_change");
            int i=Add(terminal?(s.PlayerDead?"death":s.AllEnemiesDead?"victory":"unsupported_terminal"):"decision");
            var n=nodes[i];
            n.Belief=bag.Export();n.AtCall=calls;
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
            if (observed.Length!=0 && !cheap)
            {
                bool critical=GoalExpansion(s,moves,joint,observed);
                n.Approximation=critical?"goal_expand":"ordinary_combinations";
                Count(n.Approximation);
                cheap=!critical && mode=="reduced";
            }
            if (depth>=9) {n.Approximation="depth_cap";Count("depth_cap");return i;}
            var seen=new HashSet<string>();
            foreach(var m in moves.OrderBy(m=>m.Order).ThenByDescending(m=>m.Strength))
            {
                if(cheap && (m.Draw || m.Role=="special")){Count("ordinary_skip");continue;}
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
                decisions.Enqueue(()=>n.Edges.Add(new(m.Menu,Play(s,m,bag,nextSleep,depth,[],cheap))));
            }
            return i;
        }
        // Bounded subset search uses one target per card, pays both resources and keeps joint coordinates.
        private bool GoalExpansion(SimulationSnapshot s,Move[] moves,int[] joint,string[] observed)
        {
            var pc=s.Simulator.State.GetPlayerCombatState(owner._player);
            var groups=moves.GroupBy(m=>m.Menu.Card!.Value).ToArray();
            int work=0;
            bool Search(int k,int energy,int stars,int[] point,bool used)
            {
                if(++work>512){Count("goal_estimate_limit");return true;}
                if(used && !front.Any(f=>Dominates(f,point)))return true;
                if(k>=groups.Length || k>=8)return false;
                foreach(var m in groups[k])
                {
                    int cost=m.Menu.Cost??0, star=m.Menu.StarCost??0;
                    if(cost>energy || star>stars)continue;
                    bool found=observed.Contains(TurnDrawTape.Type(pc.Hand.Cards[groups[k].Key]));
                    if(found && m.Role is "strength" or "dexterity" or "engine" or "energy" or "vulnerable")return true;
                    var next=(int[])point.Clone();
                    next[1]+=m.Block;next[2]-=cost;
                    if(m.EnemyIndex>=0)next[6+m.EnemyIndex]=Math.Min(0,next[6+m.EnemyIndex]+m.Damage);
                    if(Search(k+1,energy-cost,stars-star,next,used||found))return true;
                }
                return Search(k+1,energy,stars,point,used);
            }
            return Search(0,s.Energy,pc.Stars,joint,false);
        }
        private int Play(SimulationSnapshot parent,Move move,PileLaw bag,
            Dictionary<string,Move> sleep,int depth,string[] tape,bool cheap=false)
        {
            // Keep capacity for observed chance nodes. A deterministic root can use its whole budget.
            if(calls>=(baseline && draws.Count>0?Math.Max(1,cap/2):cap)) return Stop("budget");
            calls++;
            var session=owner._pre0bSolver!.OpenInteractiveCombat(parent);
            owners.Add(session);
            var draw=owner.Observer(bag,tape,false,false);
            using(draw.Enter())
            using(var probe=new SearchProbe(true){TurnDraw=draw}.Enter())
            {
                try { session.Play(move.Plan); }
                catch(Exception) when(probe.Boundary!=null) {}
                catch(NotSupportedException) {return Stop("unsupported_action");}
                if(probe.Boundary=="public_draw")
                {
                    if(cheap) return Stop("ordinary_random_limit");
                    int c=Add("R");
                    var options=draw.Options!.OrderBy(k=>k.Key,StringComparer.Ordinal).ToArray();
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
            var nextBag=draw.Law;
            return Visit(session.Current,nextBag,sleep,depth+1,tape,cheap);
        }
    }
}
