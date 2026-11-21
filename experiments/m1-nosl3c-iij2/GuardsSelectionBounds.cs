using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;
using HarmonyLib;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Models.Cards;

namespace CombatSolver;

internal static class GuardsSelectionBounds
{
    private static readonly Lazy<(int Min, int Max)> Bounds = new(ReadDeclaration);
    internal static (int Min, int Max) Value => Bounds.Value;

    private static (int Min, int Max) ReadDeclaration()
    {
        var onPlay = AccessTools.DeclaredMethod(typeof(Guards), "OnPlay");
        var machine = onPlay.GetCustomAttribute<AsyncStateMachineAttribute>()!.StateMachineType;
        var instructions = PatchProcessor.GetOriginalInstructions(AccessTools.DeclaredMethod(machine, "MoveNext"));
        // The pinned native OnPlay constructs its hand selector preferences with two
        // integer operands. Read that declaration without running the card effects.
        int constructor = Enumerable.Range(0, instructions.Count).Single(index =>
            instructions[index].opcode == OpCodes.Call &&
            instructions[index].operand is ConstructorInfo ctor &&
            ctor.DeclaringType == typeof(CardSelectorPrefs) &&
            ctor.GetParameters().Select(parameter => parameter.ParameterType).Skip(1)
                .SequenceEqual(new[] { typeof(int), typeof(int) }));
        if (!instructions.Skip(constructor + 1).Take(10).Any(instruction =>
            instruction.operand is MethodInfo method && method.DeclaringType == typeof(CardSelectCmd)
                && method.Name == nameof(CardSelectCmd.FromHand)))
            throw new InvalidOperationException("Guards native hand selector declaration changed.");

        return (ReadBound(instructions[constructor - 2]), ReadBound(instructions[constructor - 1]));
    }

    private static int ReadBound(CodeInstruction instruction)
    {
        if (instruction.LoadsConstant(0L))
            return 0;
        if (instruction.opcode == OpCodes.Ldc_I4 && instruction.operand is int bound)
            return bound;
        throw new InvalidOperationException("Unexpected Guards selection bound operand.");
    }
}
