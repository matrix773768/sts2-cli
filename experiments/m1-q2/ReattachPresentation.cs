using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;
using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.Models;

namespace OfflineSearchHarness;

// Opt-in presentation bypass. Leave native reattachment and its await intact.
internal static class ReattachPresentation
{
    internal static void Install()
    {
        Type segment = typeof(MonsterModel).Assembly.GetType(
            "MegaCrit.Sts2.Core.Models.Monsters.DecimillipedeSegment", throwOnError: true)!;
        MethodInfo method = AccessTools.Method(segment, "ReattachMove");
        var moveNext = AccessTools.Method(method.GetCustomAttribute<AsyncStateMachineAttribute>()!.StateMachineType, "MoveNext");
        new Harmony("m1-q2.reattach-presentation").Patch(moveNext, transpiler:
            new HarmonyMethod(AccessTools.Method(typeof(ReattachPresentation), nameof(ReplaceVisualCalls))));
    }

    private static IEnumerable<CodeInstruction> ReplaceVisualCalls(IEnumerable<CodeInstruction> instructions)
    {
        var output = instructions.ToList();
        int loadCount = 0, textureCount = 0;
        foreach (var item in output)
        {
            if (item.operand is not MethodInfo method)
                continue;
            if (method.DeclaringType == typeof(ResourceLoader) && method.Name == "Load"
                && method.ReturnType == typeof(Texture2D) && method.GetParameters().Length == 3)
            {
                item.opcode = OpCodes.Call;
                item.operand = AccessTools.Method(typeof(ReattachPresentation), nameof(SkipLoad));
                loadCount++;
            }
            else if (method.DeclaringType?.Name == "DecimillipedeSegment" && method.Name == "ChangePhobiaModeTexture")
            {
                item.opcode = OpCodes.Call;
                item.operand = AccessTools.Method(typeof(ReattachPresentation), nameof(SkipTexture));
                textureCount++;
            }
        }
        if (loadCount != 1 || textureCount != 1)
            throw new InvalidOperationException("Unexpected Decimillipede visual IL");
        return output;
    }

    private static Texture2D? SkipLoad(string path, string? hint, ResourceLoader.CacheMode cacheMode) => null;
    private static void SkipTexture(object segment, Texture2D? texture)
        => Console.WriteLine("Q2_REATTACH_PRESENTATION_BYPASSED");
}
