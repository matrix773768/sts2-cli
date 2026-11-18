using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;
using CombatSolver;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;

namespace OfflineSearchHarness;

internal sealed class RiskAudit(CombatState combat, Player player)
{
    internal sealed record PublicRisk(int Gambit, int? Sandpit);
    internal int Step { get; set; }
    internal List<object> Events { get; } = [];
    private static RiskAudit? _active;

    internal PublicRisk Observe()
        => new(player.Creature.Powers.SingleOrDefault(p => p.Id.Entry == "THE_GAMBIT_POWER")?.Amount ?? 0,
            combat.Enemies.SelectMany(e => e.Powers).SingleOrDefault(p => p.Id.Entry == "SANDPIT_POWER")?.Amount);

    internal void Install()
    {
        _active = this;
        var patch = new Harmony("m1-q4.risk-audit");
        Install(patch, "TheGambitPower", "AfterDamageReceived", nameof(Gambit), [typeof(Creature), typeof(bool)]);
        Install(patch, "SandpitPower", "AfterRemoved", nameof(Sandpit), [typeof(Creature), typeof(CardModel), typeof(bool)]);
    }

    private static void Install(Harmony patch, string type, string method, string wrapper, Type[] parameters)
    {
        Type power = typeof(PowerModel).Assembly.GetType($"MegaCrit.Sts2.Core.Models.Powers.{type}", throwOnError: true)!;
        MethodInfo original = AccessTools.Method(power, method);
        MethodInfo moveNext = AccessTools.Method(original.GetCustomAttribute<AsyncStateMachineAttribute>()!.StateMachineType, "MoveNext");
        Wrappers.Add(moveNext, (AccessTools.Method(typeof(CreatureCmd), "Kill", parameters),
            AccessTools.Method(typeof(RiskAudit), wrapper)));
        patch.Patch(moveNext, transpiler: new HarmonyMethod(AccessTools.Method(typeof(RiskAudit), nameof(InstrumentKill))));
    }

    private static readonly Dictionary<MethodBase, (MethodInfo Original, MethodInfo Wrapper)> Wrappers = [];
    private static IEnumerable<CodeInstruction> InstrumentKill(IEnumerable<CodeInstruction> instructions, MethodBase original)
    {
        var body = instructions.ToList();
        var (kill, wrapper) = Wrappers[original];
        var matches = body.Where(instruction => instruction.Calls(kill)).ToArray();
        if (matches.Length != 1) throw new InvalidOperationException("Unexpected lethal IL");
        matches[0].opcode = OpCodes.Call;
        matches[0].operand = wrapper;
        return body;
    }

    private static Task Gambit(Creature target, bool force)
    {
        _active?.Mark("THE_GAMBIT_POWER", target);
        return CreatureCmd.Kill(target, force);
    }

    private static Task Sandpit(Creature target, CardModel? source, bool force)
    {
        _active?.Mark("SANDPIT_POWER", target);
        return CreatureCmd.Kill(target, source, force);
    }

    private void Mark(string cause, Creature target)
    {
        if (ReferenceEquals(target, player.Creature))
            Events.Add(new { step = Step, cause, hpBeforeKill = target.CurrentHp,
                turn = player.PlayerCombatState?.TurnNumber });
    }
}
