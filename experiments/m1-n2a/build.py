"""Build a private N2A worker using the S3B synthetic host."""
from pathlib import Path
import runpy
import shutil

HERE = Path(__file__).resolve().parent
s3b = runpy.run_path(str(HERE.parent / "m1-s3b/build_host.py"))
s3a = s3b["s3a"]


def stage(src):
    s3b["stage"](src)
    shutil.copyfile(HERE / "Episode.cs", src / "Episode.cs")
    probe = src / "IntegrationProbe.cs"
    s3a.edit(probe, '        if (command == "i1_release")', '''        if (command == "i1_n2_close")
        {
            _episode?.Dispose();
            _episode = null;
            return new() { ["type"] = "n2_closed" };
        }
        if (command == "i1_n2_step")
            return new() { ["type"] = "n2_step",
                ["episode"] = (_episode ?? throw new InvalidOperationException("Reset first")).EpisodeStep(cmd) };
        if (command == "i1_release")''')
    s3a.edit(probe, '            case "i1_f3b":',
             '            case "i1_n2_reset":\n            case "i1_f3b":')
    s3a.edit(probe, 'command is "i1_f3b" or "i1_f4"',
             'command is "i1_f3b" or "i1_f4" or "i1_n2_reset"')
    host = src / "Host.cs"
    s3a.edit(host, '    private static Dictionary<string, object?> RunFirstWin', '''
    private static FirstWin? _episode;

    private static Dictionary<string, object?> RunFirstWin''')
    s3a.edit(host, '        int cap = request.GetProperty', '''        bool episode = request.GetProperty("cmd").GetString() == "i1_n2_reset";
        if (episode)
        {
            _episode?.Dispose();
            _episode = null;
        }
        int cap = request.GetProperty''')
    s3a.edit(host, '        using var search = new FirstWin', '        var search = new FirstWin')
    s3a.edit(host, '        return new() { ["type"] = "f3b_result", ["root_prepare_ms"]', '''        if (episode)
        {
            _episode = search;
            return new() { ["type"] = "n2_reset", ["root_prepare_ms"] = clock.Elapsed.TotalMilliseconds,
                ["episode"] = search.EpisodeView() };
        }
        using var owned = search;
        return new() { ["type"] = "f3b_result", ["root_prepare_ms"]''')


if __name__ == "__main__":
    i1 = s3a.b1b.b1a.i1
    i1.build(i1.ROOT / "logs/m1-n2a-build", stage)
