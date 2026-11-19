"""Build B1B with runtime Solver attestation and a read-only full act catalog."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("s3a_b1b", HERE.parent / "m1-b1b/build_probe.py")
b1b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1b)
edit = b1b.b1a.edit


def stage(src):
    b1b.stage(src)
    edit(src / "SyntheticCatalog.cs", "ModelDb.ActsByIndex.Take(2)", "ModelDb.ActsByIndex")
    edit(src / "IntegrationProbe.cs", '        if (command == "i1_release")', '''        if (command == "i1_s3a_identity")
        {
            var assembly = typeof(CombatBeamSolver).Assembly;
            return new() { ["type"] = "solver_identity",
                ["version"] = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion,
                ["sha256"] = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(
                    File.ReadAllBytes(assembly.Location))) };
        }
        if (command == "i1_release")''')


if __name__ == "__main__":
    b1b.b1a.i1.build(b1b.b1a.ROOT / "logs/m1-s3a-build", stage)
