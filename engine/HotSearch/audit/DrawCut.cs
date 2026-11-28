using System.Reflection;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;

internal static class DrawCut
{
    internal static object? Last;
    internal static void Attach(){
        var target=typeof(CardPileCmd).GetMethods(BindingFlags.Static|BindingFlags.Public|BindingFlags.NonPublic)
            .Single(m=>m.Name=="DrawInternal" && m.GetParameters().Any(p=>p.Name=="fromHandDraw"));
        new Harmony("sts2.infra.h4.audit.draw").Patch(target,prefix:new HarmonyMethod(typeof(DrawCut),nameof(Capture)));
    }
    public static void Capture(Player player,bool fromHandDraw){
        if(!fromHandDraw)return;
        var pc=player.PlayerCombatState!;
        object Card(CardModel c)=>new{type=c.Id.Entry+"#"+(c.IsUpgraded?1:0),cost=c.EnergyCost?.GetResolved()??0,
            vars=c.DynamicVars.Values.ToDictionary(v=>v.Name,v=>v.BaseValue)};
        var live=CombatManager.Instance.DebugOnlyGetState()!;
        Last=new{hp=player.Creature.CurrentHp,max_hp=player.Creature.MaxHp,draw_count=pc.DrawPile.Cards.Count,
            hand=pc.Hand.Cards.Select(Card).ToArray(),discard=pc.DiscardPile.Cards.Select(Card).ToArray(),exhaust=pc.ExhaustPile.Cards.Select(Card).ToArray(),
            enemies=live.Enemies.Select(c=>new{species=c.Monster!.Id.Entry,hp=c.CurrentHp}).ToArray()};
    }
}
