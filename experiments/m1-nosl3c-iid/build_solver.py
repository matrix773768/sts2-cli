"""Stage the shared team resource mirror in the frozen II-B Solver build."""
from hashlib import sha256
import json
from pathlib import Path
import runpy
import subprocess
from types import FunctionType, SimpleNamespace

HERE = Path(__file__).resolve().parent
BASE = runpy.run_path(str(HERE.parent / "m1-nosl3c-iib/build_solver.py"))


def stage(command, **kwargs):
    project = Path(command[2])
    directory = project.parent / "src/Engine/InCombat/Mirrors/Cards/OnPlay"
    registry = directory / "CardOnPlayMirrors.cs"
    effects = directory / "CardDrawCardMirrors.cs"
    edits = [
        (registry, "        registry.Register<Adrenaline>", """        registry.Register<EnergySurge>((card, context) => CardDrawCardMirrors.GainTeamEnergy(context, card.DynamicVars.Energy.IntValue));
        registry.Register<Adrenaline>"""),
        (effects, "    public static void AdrenalineOnPlay", """    internal static void GainTeamEnergy(CardOnPlayMirrorContext context, int amount)
    {
        foreach (var player in context.State.CombatState.Players)
        {
            context.Simulator.GainEnergy(player, amount);
            if (context.Simulator.HasPendingChoice)
                return;
        }
    }

    public static void AdrenalineOnPlay"""),
    ]
    for path, old, new in edits:
        code = path.read_text(encoding="utf-8")
        if code.count(old) != 1:
            raise ValueError(f"Unexpected source for {path.name}")
        path.write_text(code.replace(old, new), encoding="utf-8")
    subprocess.run(command, **kwargs)
    output = Path(command[-1]).parent
    (output / "team-resources.json").write_text(json.dumps(dict(
        source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        mirrors={p.name: sha256(p.read_bytes()).hexdigest() for p, _, _ in edits}),
        indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main = BASE["main"]
    FunctionType(main.__code__, main.__globals__ | {
        "VERSION": "0.51.5-iid.1", "subprocess": SimpleNamespace(run=stage)})()
