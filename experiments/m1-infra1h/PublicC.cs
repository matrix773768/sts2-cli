using System.Text.Json;
using CombatSolver.HotKernel;

// Diagnostic side of the private world. Only public quantities are emitted.
// The hidden draw pile and private RNG have no serialization path here.
public static partial class HotWorld
{
    private static object? publicC;
    private static void CapturePublicC(in CombatHotState s,HotRules r,int draw)
    {
        var powers=new List<object>[3+HotLimits.MaxEnemies];
        for(int i=0;i<powers.Length;i++)powers[i]=[];
        for(int i=0;i<s.PowerCount;i++){
            var power=s.Powers[i];
            if(power.OwnerSlot<powers.Length)powers[power.OwnerSlot].Add(new{id=r.Powers[power.PowerDefId].Entry,amount=power.Amount});
        }
        var enemies=new List<object>();
        for(int i=0;i<s.EnemyCount;i++){
            var e=s.Enemies[i];
            var machine=r.GetMonsterMachine(e.MonsterDefId);
            string? move=machine!=null && e.CurrentMoveNode>=0 && e.CurrentMoveNode<machine.Nodes.Length?
                machine.Nodes[e.CurrentMoveNode].MoveId:null;
            enemies.Add(new{slot=i,species=r.Monsters[e.MonsterDefId].Entry,hp=e.Vital.CurrentHp,
                max_hp=e.Vital.MaxHp,block=e.Vital.Block,move,powers=powers[3+i]});
        }
        publicC=new{turn=s.PlayerTurnNumber,hp=s.Player.CurrentHp,max_hp=s.Player.MaxHp,block=s.Player.Block,
            energy=s.Energy,stars=s.Stars,draw_count=(int)s.DrawCount,draw,powers=powers[0],enemies,
            hand=Zone(in s,r,HotPileKind.Hand),discard=Zone(in s,r,HotPileKind.Discard),exhaust=Zone(in s,r,HotPileKind.Exhaust)};
    }
    public static JsonElement ExportC()=>JsonSerializer.SerializeToElement(publicC);
}
