"""Bind generated selections to their captured option instances."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
III8 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iii8/build_solver.py"))
IIH = III8["IIH"]


def lifecycle(source):
    III8["lifecycle"](source)
    edit = IIH["edit"]
    edit(source / "Search/CardChoiceSupport.cs",
         """            return RangeSpec(
                owner,
                PlanChoiceEffect.GenerateToHand,
                PileType.None,
                minCount,
                1,
                generated.Options);""",
         """            return GeneratedSpec(generated, minCount);""")
    edit(source / "Search/CardChoiceSupport.cs",
         "    private static CardChoiceSpec RangeSpec(",
         """    internal static CardChoiceSpec GeneratedSpec(
        CombatPredictionCardGenerationOptionsEntry generated, int minCount)
    {
        // Generated options are unattached until confirmation. Their source is the
        // captured generation batch, and tokens use occurrences within that batch.
        var options = generated.Options.ToArray();
        return new CardChoiceSpec(PlanChoiceEffect.GenerateToHand, PileType.None,
            minCount, 1, options, options, ReplacementValue: 0d);
    }

    private static CardChoiceSpec RangeSpec(""")
    edit(source / "Search/PotionChoiceSupport.cs",
         """            return RangeSpec(
                state,
                PlanChoiceEffect.GenerateToHand,
                PileType.None,
                0,
                1,
                generated.Options);""",
         """            return CardChoiceSupport.GeneratedSpec(generated, minCount: 0);""")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iij.1", subprocess=SimpleNamespace(run=stage)))()
