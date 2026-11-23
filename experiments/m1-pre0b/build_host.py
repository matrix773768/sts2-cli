"""Build an isolated PRE0B host with compact prediction responses."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy
import shutil

PRE0 = Path(__file__).resolve().parent.parent / "m1-pre0"
pre0 = runpy.run_path(str(PRE0 / "build_host.py"))
edit = pre0["edit"]


def stage(src):
    pre0["stage"](src)
    edit(src.parent / "GodotStubs/UI.cs", "public class CanvasItem : Node\n{",
         "public class CanvasItem : Node\n{\n    public void SetVisible(bool value) => Visible = value;")
    episode = src / "InteractiveEpisode.cs"
    shutil.copyfile(Path(__file__).with_name("KnowledgeChoice.cs"), src / "KnowledgeChoice.cs")
    edit(episode, "        _interactive = solver.GetType()", "        _pre0bSolver = solver;\n        _interactive = solver.GetType()")
    edit(episode, '        string status = _interactiveStop ?? (waiting && !snapshot.HasRisk ? "active" : StatusOf(snapshot));',
         '        var knowledge = KnowledgeChoice(snapshot);\n'
         '        string status = _interactiveStop ?? ((waiting || knowledge != null) && !snapshot.HasRisk ? "active" : StatusOf(snapshot));')
    edit(episode, '            if (status == "active" && waiting)', """            if (status == "active" && knowledge != null)
            {
                var candidates = knowledge.OptionIds.Select((id, i) => new NoslCard(i, id, 0, null, null, null, null, null)).ToArray();
                var actions = new List<NoslAction>();
                if (_selection.Count == 0)
                    foreach (var card in candidates)
                        actions.Add(new(actions.Count, "select_candidate", Choice: card.Index));
                else
                    actions.Add(new(0, "confirm_selection"));
                observation = ObserveNosl(_root, snapshot, actions, new
                {
                    phase = "choice", effect = "ApplyKnowledgeCurse", pile = "None",
                    timing = "EnemyTurn", min = 1, max = 1, candidates, selected = _selection.ToArray(),
                });
                _selectionMenu = actions;
            }
            else if (status == "active" && waiting)""")
    edit(episode, '        if (!waiting && StatusOf(InteractiveProperty<SimulationSnapshot>("Current")) != "active")',
         '        var knowledge = KnowledgeChoice(InteractiveProperty<SimulationSnapshot>("Current"));\n'
         '        waiting |= knowledge != null;\n'
         '        if (!waiting && StatusOf(InteractiveProperty<SimulationSnapshot>("Current")) != "active")')
    edit(episode, '                InteractiveInvoke("Select", _selection.ToArray());',
         '                if (knowledge != null) SubmitKnowledgeChoice(knowledge, _selection.Single());\n'
         '                else InteractiveInvoke("Select", _selection.ToArray());')
    edit(episode, """            interaction_trace = _interactive!.GetType()
                .GetProperty("InteractionTrace", BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(_interactive),
            audit_action = InteractiveProperty<PlanAction?>("LastCompletedAction"),
            audit_stamp = waiting ? null : Digest(snapshot),
""", "")
    edit(src / "Program.cs", 'else if (kind == "pre0_start")', '''else if (kind == "i1_n2_step")
                {
                    using var timer = ProbeTiming.Begin("predict_step");
                    result = IntegrationProbe.Run(sim, cmd);
                }
                else if (kind == "pre0_start")''')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    pre0["base"].build(output, stage)
    binary = output / "Headless/bin/Debug/net9.0"
    artifacts = {name: {"sha256": sha256((binary / name).read_bytes()).hexdigest()}
                 for name in ("OfflineSearchHarness.dll", "GodotSharp.dll")}
    (output / "build.json").write_text(json.dumps(dict(version="PRE0B-host.v2", artifacts=artifacts),
                                                 indent=2), encoding="utf-8")
