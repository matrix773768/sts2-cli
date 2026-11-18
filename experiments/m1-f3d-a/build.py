"""Build the isolated S2A host with one-action fixed prediction diagnostics."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("f3da_s2a", HERE.parent / "m1-s2a/build.py")
s2a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s2a)


def stage(src):
    s2a.stage(src)
    edit = s2a.s1.f3b.f3a.f2.replace
    probe = src / "IntegrationProbe.cs"
    edit(probe, '        bool fixedRoute = cmd.TryGetProperty("fixed_actions", out var recorded);',
         '''        bool fixedRoute = cmd.TryGetProperty("fixed_actions", out var recorded);
        bool fixedPrefix = fixedRoute && cmd.TryGetProperty("fixed_prefix", out var prefix)
            && prefix.GetBoolean();
        if (fixedPrefix && recorded.GetArrayLength() != 1)
            throw new ArgumentException("Fixed prefix probe requires exactly one action");''')
    edit(probe, '            if (!state.AllEnemiesDead || state.PlayerDead) throw new InvalidOperationException("Prediction replay did not win");',
         '''            if (fixedPrefix)
            {
                response["status"] = "fixed_prefix";
                response["prefix_boundary"] = state.BoundaryReason.ToString();
                response["prefix_risk"] = state.HasRisk;
                response["prefix_terminal"] = state.TerminalStamp != null;
            }
            else if (!state.AllEnemiesDead || state.PlayerDead)
                throw new InvalidOperationException("Prediction replay did not win");''')
    edit(probe, '        response["predicted_win"] = true;',
         '        if (!fixedPrefix) response["predicted_win"] = true;')


if __name__ == "__main__":
    i1 = s2a.s1.f3b.f3a.f2.f1.i1
    i1.build(i1.ROOT / "logs/m1-f3d-a-build", stage)
