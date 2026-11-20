"""Isolated IID host with an offline, unpruned direct Replay entry."""
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
BASE = runpy.run_path(str(HERE.parent / "m1-nosl3c-iid/build_host.py"))
HOST = "m1-nosl3c-iif-build"


def stage(src):
    BASE["stage"](src)
    edit = BASE["BASE"]["BASE"]["BINDING"].edit
    edit(src / "IntegrationProbe.cs", '        if (command == "i1_iid_prediction_text")',
         '        if (command == "i1_iif_current_plan")\n'
         '            return (_episode ?? throw new InvalidOperationException("Reset first")).CurrentPlan(cmd);\n'
         '        if (command == "i1_iid_prediction_text")')
    edit(src / "InteractiveEpisode.cs", "    internal string PredictionText()", '''
    internal Dictionary<string, object?> CurrentPlan(JsonElement request)
    {
        int index = request.GetProperty("index").GetInt32();
        if (request.GetProperty("position").GetInt32() != _decisionPosition ||
            InteractiveProperty<bool>("Waiting") || _episodeMenu == null || index < 0 || index >= _episodeMenu.Length)
            throw new InvalidOperationException("No current combat plan for the requested menu slot");
        return new() { ["type"] = "current_plan", ["plan"] = _episodeMenu[index].Action };
    }

    internal string PredictionText()''')
    edit(src / "IntegrationProbe.cs", '            case "i1_capture": break;',
         '            case "i1_iif_direct":\n            case "i1_capture": break;')
    edit(src / "IntegrationProbe.cs", "        if (actions.FirstOrDefault(action => !TeacherChoice.Supports(action))",
         '''        if (command == "i1_iif_direct")
        {
            if (!fixedRoute) throw new ArgumentException("Direct replay requires fixed_actions");
            var current = Step(solver, null, null);
            var boundaries = new List<object>();
            try
            {
                foreach (var action in actions)
                {
                    var next = Step(solver, current, action);
                    current.ReleaseSimulator();
                    current = next;
                    boundaries.Add(new { boundary = current.BoundaryReason.ToString(), risk = current.HasRisk,
                        death = current.PlayerDead, win = current.AllEnemiesDead, hp = current.PlayerHp,
                        gaps = current.PredictionGaps.Select(g => g.Key + ": " + g.Reason).ToArray(),
                        powers = ((SimulatedCombatState)current.Simulator.State.CombatState).EffectivePowers()
                            .Select(p => new { id = p.Id.Entry, amount = p.Amount }).ToArray() });
                    if (current.HasRisk || current.BoundaryReason != SearchBoundaryReason.None ||
                        current.PlayerDead || current.AllEnemiesDead)
                        break;
                }
                return new() { ["type"] = "direct_replay", ["boundaries"] = boundaries };
            }
            finally { current.ReleaseSimulator(); }
        }
        if (actions.FirstOrDefault(action => !TeacherChoice.Supports(action))''')


if __name__ == "__main__":
    i1 = BASE["BASE"]["BASE"]["BINDING"].b1b.b1a.i1
    i1.build(i1.ROOT / "logs" / HOST, stage)
