"""Stage the F4 harness with a fixed-prefix probe and loaded assembly identity."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("e3f_f4", HERE.parent / "m1-f4/build.py")
f4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f4)
i1 = f4.f3db.f3da.s2a.s1.f3b.f3a.f2.f1.i1
edit = f4.f3db.f3da.s2a.s1.f3b.f3a.f2.replace


def stage(src):
    f4.stage(src)
    probe = src / "IntegrationProbe.cs"
    edit(probe, '        if (command == "i1_release")', '''        if (command == "i1_e3f_identity")
        {
            var assembly = typeof(CombatBeamSolver).Assembly;
            return new() { ["type"] = "solver_identity",
                ["version"] = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion,
                ["sha256"] = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(
                    File.ReadAllBytes(assembly.Location))) };
        }
        if (command == "i1_release")''')
    edit(probe, 'if (fixedPrefix && recorded.GetArrayLength() != 1)\n            throw new ArgumentException("Fixed prefix probe requires exactly one action");',
         'if (fixedPrefix && recorded.GetArrayLength() is < 1 or > 48)\n            throw new ArgumentException("Fixed prefix probe requires 1–48 actions");')


if __name__ == "__main__":
    i1.build(i1.ROOT / "logs/m1-e3f-build", stage)
