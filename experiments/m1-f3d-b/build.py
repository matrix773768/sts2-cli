"""Build the existing S2A/F3D-A host with an observational terminal window probe."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("f3db_f3da", HERE.parent / "m1-f3d-a/build.py")
f3da = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f3da)


def stage(src):
    f3da.stage(src)
    edit = f3da.s2a.s1.f3b.f3a.f2.replace
    probe = src / "IntegrationProbe.cs"
    edit(probe, '            case "i1_step":\n', '''            case "i1_step":
                var beforeWindow = (object?)null;
''')
    edit(probe, '                string kind = action.GetProperty("kind").GetString()!;',
         '''                string kind = action.GetProperty("kind").GetString()!;
                if (kind == "EndTurn")
                    beforeWindow = ObserveWindow(live);''')
    edit(probe, '                    ["terminal"] = _terminal != null, ["decision"] = decision,',
         '''                    ["terminal"] = _terminal != null, ["decision"] = decision,
                    ["before_window"] = _terminal != null ? beforeWindow : null,
                    ["terminal_window"] = _terminal != null ? _terminalWindow : null,''')
    edit(probe, '            _terminal = null;', '            _terminal = null;\n            _terminalWindow = null;')
    edit(probe, '    private static void ObserveTerminal() => _terminal ??= _nativeCapture?.Invoke();',
         '''    private static object? _terminalWindow;

    private static object ObserveWindow(CombatState combat)
    {
        var history = CombatManager.Instance.History;
        return new
        {
            side = combat.CurrentSide.ToString(),
            round = combat.RoundNumber,
            card_plays = history.CardPlaysStarted.Count(),
            card_draws = history.Entries.Count(e => e.GetType().Name == "CardDrawnEntry"),
            plays_in_window = history.CardPlaysStarted.Count(e => e.HappenedThisTurn(combat)),
            enemy_hp = combat.Enemies.Sum(e => e.CurrentHp),
        };
    }

    private static void ObserveTerminal()
    {
        if (_terminal != null || _nativeCapture is null || _boundCombat is null)
            return;
        _terminalWindow = ObserveWindow(_boundCombat);
        _terminal = _nativeCapture();
    }''')


if __name__ == "__main__":
    i1 = f3da.s2a.s1.f3b.f3a.f2.f1.i1
    i1.build(i1.ROOT / "logs/m1-f3d-b-build", stage)
