"""Build the II-H.5 candidate on top of the II-H.4 rules."""
from pathlib import Path
import runpy
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
IIH4 = runpy.run_path(str(HERE.parent / "m1-nosl3c-iih4/build_solver.py"))
IIH = IIH4["IIH"]
VERSION = "0.51.5-iih.5.1"


def lifecycle(source):
    IIH4["duration_and_orb_power"](source)
    edit = IIH["edit"]
    semantics = source / "Prediction/MonsterMoveSemantics.cs"
    edit(semantics, """        if (playerDied)
            return true;""", """        // GasBomb.ExplodeMove awaits the attack, then kills its owner even
        // when the attack kills the player. Finish that tail before publishing defeat.
        if (playerDied && !(move.Owner.Monster is GasBomb && move.Move.Id == "EXPLODE_MOVE"))
            return true;""")
    effects = source / "Prediction/MonsterMoveEffects.cs"
    edit(effects, """            case ("GasBomb", "EXPLODE_MOVE"):
                if (simulator.State.GetCreature(move.Owner).IsDead) return true;
                using (simulator.PushDamageSource(
                    CombatDamageSource.For(CombatDamageSourceKind.MonsterMove, move.Owner.Monster?.Id.Entry)))
                {
                    simulator.Kill(move.Owner, force: true);
                }""", """            case ("GasBomb", "EXPLODE_MOVE"):
                if (simulator.State.GetCreature(move.Owner).IsDead) return true;
                using (simulator.PushDamageSource(
                    CombatDamageSource.For(CombatDamageSourceKind.MonsterMove, move.Owner.Monster?.Id.Entry)))
                {
                    simulator.Kill(move.Owner);
                }""")


def stage(command, **kwargs):
    upstream = IIH["stage"]
    patched = FunctionType(upstream.__code__, upstream.__globals__ |
                           {"duration_lifecycle": lifecycle})
    patched(command, **kwargs)


if __name__ == "__main__":
    main = IIH["BASE"]["IIG"]["BASE"]["main"]
    FunctionType(main.__code__, main.__globals__ |
                 dict(VERSION=VERSION, subprocess=SimpleNamespace(run=stage)))()
