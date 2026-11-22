"""Build II-K.2.1 with the native phase-one victory check after orb passives."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIK1 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iik1/build_solver.py"))
IIH = IIK1["IIH"]


def lifecycle(source):
    IIK1["lifecycle"](source)
    IIH["edit"](
        source / "Engine/InCombat/Simulation/CombatPredictionSimulator.EndTurn.cs",
        """    internal bool SimulateEndPlayerTurnAfterOrbPassives(int playerTurn)
    {
        if (IsOverOrEnding)
            return true;
        var playersEndingTurn = State.CombatState.Players;""",
        """    internal bool SimulateEndPlayerTurnAfterOrbPassives(int playerTurn)
    {
        // DoTurnEnd skips its work when combat is ending, but the phase-one
        // victory check must still lock the terminal state before switching sides.
        var playersEndingTurn = State.CombatState.Players;""",
    )


def stage(command, **kwargs):
    upstream = IIH["stage"]
    FunctionType(upstream.__code__, upstream.__globals__ |
                 {"duration_lifecycle": lifecycle})(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ | dict(
        VERSION="0.51.5-iik.2.1", subprocess=SimpleNamespace(run=stage)))()
