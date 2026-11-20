"""Stage the isolated v3 host on the no-resource synthetic host."""
from pathlib import Path
import runpy
import shutil

HERE = Path(__file__).resolve().parent
BASE = runpy.run_path(str(HERE.parent / "m1-nosl3c-iia/build.py"))
HOST = "m1-nosl3c-iib-build"


def stage(src):
    BASE["stage"](src)
    edit = BASE["BINDING"].edit
    shutil.copyfile(HERE / "InteractiveEpisode.cs", src / "InteractiveEpisode.cs")
    host = src / "Host.cs"
    edit(host, '            _episode = search;', '            search.OpenInteractive(solver);\n            _episode = search;')
    edit(host, 'search.EpisodeView()', 'search.InteractiveView()')
    probe = src / "IntegrationProbe.cs"
    edit(probe, '.EpisodeStep(cmd)', '.InteractiveStep(cmd)')
    edit(probe, '        if (command == "i1_n2_close")', '''        if (command == "i1_iib_native_stamp")
        {
            if (_nativeCapture == null) throw new InvalidOperationException("Begin native audit first");
            return new() { ["type"] = "i1_state", ["state"] = _terminal ?? _nativeCapture(),
                ["terminal"] = _terminal != null };
        }
        if (command == "i1_n2_close")''')
    edit(src / "FirstWin.cs", '    public void Dispose()\n    {', '    public void Dispose()\n    {\n        CloseInteractive();')

    episode = src / "NoslPublicEpisode.cs"
    edit(episode, 'private object ObserveNosl(Node node)', '''private object ObserveNosl(Node node,
        SimulationSnapshot? overrideState = null, List<NoslAction>? choices = null, object? decision = null)''')
    edit(episode, 'var snapshot = node.State!;', 'var snapshot = overrideState ?? node.State!;')
    edit(episode, 'for (int index = 0; index < hand.Count; index++)',
         'for (int index = 0; choices == null && index < hand.Count; index++)')
    code = episode.read_text(encoding="utf-8")
    begin = code.index("            var choiceEffect =")
    end = code.index("            string key", begin)
    code = code[:begin] + code[end:]
    begin = code.index("                foreach (var (choice, zone, token)")
    end = code.index("\n            }", begin)
    code = code[:begin] + '''                Add(new(actions.Count, "play_card", index, target, Cost: cost, Preview: preview,
                    StarCost: stars, EnergyX: card.Preview.EnergyCost.CostsX, StarX: card.Preview.HasStarCostX), plan);''' + code[end:]
    begin = code.index("        for (int slot = 0; slot < _player.PotionSlots.Count; slot++)")
    end = code.index("        _episodeMenu = ", begin)
    code = code[:begin] + '''        if (choices == null)
            Add(new(actions.Count, "end_turn"), new(PlanActionKind.EndTurn, snapshot.Turn));
''' + code[end:]
    code = code.replace('schema = "sts2.nosl_observation.v2",',
                        'schema = "sts2.nosl_observation.v3",\n            decision = decision ?? new { phase = "combat" },')
    code = code.replace('            actions,', '            actions = choices ?? actions,')
    episode.write_text(code, encoding="utf-8")


if __name__ == "__main__":
    i1 = BASE["BINDING"].b1b.b1a.i1
    i1.build(i1.ROOT / "logs" / HOST, stage)
