using System.Text.Json;
using CombatSolver.HotKernel;
using MegaCrit.Sts2.Core.Combat;

// Private trajectory verifier. This object and its RNG never reach the public search.
public static class HotWorld
{
    private static HotRules? rules;
    private static CombatHotState world;
    private static HotColdSidecar? cold;
    private static readonly HotExecScratch scratch=new();
    private static object? captured;
    private static string CardName(HotRules r, HotCard c)=>r.Cards[c.CardDefId].Entry+"#"+c.UpgradeLevel;
    private static string[] Zone(in CombatHotState s,HotRules r,HotPileKind pile)
    {
        int n=HotPiles.ZoneCount(in s,pile),start=HotPiles.ZoneStart(in s,pile);
        var result=new string[n];
        for(int i=0;i<n;i++)result[i]=CardName(r,s.Cards[start+i]);
        return result;
    }
    private static string[] CoreZone(JsonElement obs,string name)=>obs.GetProperty(name).EnumerateArray()
        .Select(c=>c.GetProperty("id").GetString()+"#"+c.GetProperty("upgrade").GetInt32()).ToArray();
    private static void Capture(in CombatHotState s,HotColdSidecar? c,HotRules r,int draw)
    {
        captured=new{turn=s.PlayerTurnNumber,hp=s.Player.CurrentHp,max_hp=s.Player.MaxHp,block=s.Player.Block,
            energy=s.Energy,stars=s.Stars,draw_count=(int)s.DrawCount,draw,
            hand=Zone(in s,r,HotPileKind.Hand),discard=Zone(in s,r,HotPileKind.Discard).Order().ToArray(),
            exhaust=Zone(in s,r,HotPileKind.Exhaust).Order().ToArray()};
    }
    private static string? Compare(JsonElement episode)
    {
        string status=episode.GetProperty("status").GetString()!;
        if(status!="active")
        {
            if((status,world.TerminalOutcome) is not (("predicted_win",HotCombatOutcome.Victory) or ("death",HotCombatOutcome.Defeat)))return "terminal_status";
            var t=episode.GetProperty("terminal_observation");
            return world.Player.CurrentHp==t.GetProperty("hp").GetInt32() && world.Player.MaxHp==t.GetProperty("max_hp").GetInt32()?null:"terminal_hp";
        }
        var h=episode.GetProperty("observation");
        if(world.TerminalOutcome!=HotCombatOutcome.Ongoing)return "early_terminal";
        foreach(var (key,value) in new (string,int)[]{("turn",world.PlayerTurnNumber),("hp",world.Player.CurrentHp),
            ("max_hp",world.Player.MaxHp),("block",world.Player.Block),("energy",world.Energy),("stars",world.Stars),("draw_count",world.DrawCount)})
            if(h.GetProperty(key).GetInt32()!=value)return key;
        foreach(var (key,pile) in new[]{("hand",HotPileKind.Hand),("discard",HotPileKind.Discard),("exhaust",HotPileKind.Exhaust)})
        {
            var a=CoreZone(h,key);var b=Zone(in world,rules!,pile);
            if(key=="exhaust"){Array.Sort(a,StringComparer.Ordinal);Array.Sort(b,StringComparer.Ordinal);}
            if(!a.SequenceEqual(b))return key;
        }
        var enemies=h.GetProperty("enemies").EnumerateArray().ToArray();
        var alive=new List<HotEnemy>();
        for(int i=0;i<world.EnemyCount;i++)
            if((world.Enemies[i].Vital.Flags&HotCreatureFlags.Alive)!=0)alive.Add(world.Enemies[i]);
        if(enemies.Length!=alive.Count)return "enemy_slots";
        for(int i=0;i<alive.Count;i++)
            if(alive[i].Vital.CurrentHp!=enemies[i].GetProperty("hp").GetInt32() ||
                alive[i].Vital.Block!=enemies[i].GetProperty("block").GetInt32())return "enemy_resources";
        return null;
    }
    public static string? Start(JsonElement episode)
    {
        var root=HotRootBuilder.BuildFromLive(CombatManager.Instance.DebugOnlyGetState()!);
        rules=root.Rules;world=root.RootState;cold=root.RootCold;
        return Compare(episode);
    }
    public static string? Step(JsonElement before,int index,JsonElement after)
    {
        var h=before.GetProperty("observation");
        var action=h.GetProperty("actions")[index];
        var kind=action.GetProperty("kind").GetString();
        HotAction play;
        if(kind=="end_turn")play=HotAction.EndTurn();
        else if(kind=="play_card")
        {
            var hand=action.GetProperty("card").GetInt32();
            var card=h.GetProperty("hand")[hand];
            if(card.GetProperty("id").GetString()!=rules!.Cards[world.Cards[hand].CardDefId].Entry ||
                card.GetProperty("upgrade").GetInt32()!=world.Cards[hand].UpgradeLevel)return "bind_card";
            int target=-1;
            if(action.TryGetProperty("target",out var t) && t.ValueKind==JsonValueKind.Number)
            {
                int rank=t.GetInt32();
                for(int i=0;i<world.EnemyCount;i++)
                    if((world.Enemies[i].Vital.Flags&HotCreatureFlags.Alive)!=0 && rank--==0){target=i;break;}
                if(target<0)return "bind_target";
            }
            play=HotAction.PlayCard(hand,target);
        }
        else return "waiting_player_selector";
        captured=null;
        InfraCObserver.BeforeDraw=Capture;
        HotStepResult result;
        try{result=HotCombatEngine.Step(ref world,ref cold,rules!,scratch,play);}
        finally{InfraCObserver.BeforeDraw=null;}
        if(result.NeedsChoice)return "waiting_player_selector";
        if(!result.Executed)return "action_rejected";
        return Compare(after);
    }
    public static string? CheckC(JsonElement episode)
    {
        bool expected=episode.TryGetProperty("observed_c",out var c) && c.ValueKind==JsonValueKind.Object;
        if(captured==null)return expected?"missing":null;
        if(!expected)return "unexpected";
        var a=JsonSerializer.SerializeToElement(captured);
        foreach(var key in new[]{"turn","hp","max_hp","block","energy","stars","draw_count"})
            if(a.GetProperty(key).GetInt32()!=c.GetProperty(key).GetInt32())return key;
        if(a.GetProperty("draw").GetInt32()!=c.GetProperty("setup").GetProperty("draw").GetInt32())return "draw";
        foreach(var k in new[]{"hand","discard","exhaust"})
        {
            var aa=a.GetProperty(k).EnumerateArray().Select(x=>x.GetString()!);
            var bb=CoreZone(c,k).AsEnumerable();
            if(k!="hand"){aa=aa.Order(StringComparer.Ordinal);bb=bb.Order(StringComparer.Ordinal);}
            if(!aa.SequenceEqual(bb))return k;
        }
        return "matched";
    }
}
