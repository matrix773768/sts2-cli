"""Build the opt-in NOSL worker atop frozen N2A.1 and LS2A trajectory code."""
from pathlib import Path
import runpy
import shutil

HERE = Path(__file__).resolve().parent
N2A = runpy.run_path(str(HERE.parent / "m1-n2a1/build.py"))
HOST = "m1-nosl3a-build"


def stage(src):
    N2A["stage"](src)
    shutil.copyfile(HERE / "PublicEpisode.cs", src / "NoslPublicEpisode.cs")
    shutil.copyfile(HERE.parent / "m1-ls2a/Trajectory.cs", src / "Ls2Trajectory.cs")
    edit = N2A["s3a"].edit
    episode = src / "Episode.cs"
    edit(episode, "Observation? observation = null;", "object? observation = null;")
    edit(episode, "observation = ObserveEpisode(node);", "observation = ObserveNosl(node);")
    edit(episode, 'status, observation, detail = _episodeDetail,',
         'status, observation, terminal_observation = status == "active" ? null : NoslTerminal(node), detail = _episodeDetail,')
    edit(src / "Host.cs", ': search.Run(arm,',
         ': request.TryGetProperty("ls2_trajectory", out var trajectory)\n'
         '                ? search.RunTrajectory(trajectory.GetString()!) : search.Run(arm,')


if __name__ == "__main__":
    i1 = N2A["s3a"].b1b.b1a.i1
    i1.build(i1.ROOT / "logs" / HOST, stage)
