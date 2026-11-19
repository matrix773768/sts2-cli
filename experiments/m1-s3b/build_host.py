"""Stage the existing full Solver diagnostic with potions explicitly disabled."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("s3b_s3a", HERE.parent / "m1-s3a/build_host.py")
s3a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s3a)


def stage(src):
    s3a.stage(src)
    s3a.edit(src / "IntegrationProbe.cs",
             "searchProfile: policy.Profile);",
             "searchProfile: policy.Profile, potionPolicyOverride: SolverPotionPolicy.Disabled);")


if __name__ == "__main__":
    s3a.b1b.b1a.i1.build(s3a.b1b.b1a.ROOT / "logs/m1-s3b-build", stage)
