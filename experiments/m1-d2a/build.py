"""Build the isolated D1 sampling host with two additional native choice contracts."""
import importlib.util
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("d2a_f3b_build", HERE.parent / "m1-f3b/build.py")
f3b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f3b)
HOST = "m1-d2a-build"


def stage(source):
    f3b.stage(source)
    shutil.copyfile(HERE / "SamplingChoiceAudit.cs", source / "SamplingChoiceAudit.cs")
    edit = f3b.f3a.f2.replace
    choices = source / "CombatChoices.cs"
    edit(choices, '        ["PREPARED"] = new("hand", "discard", 1, true),',
         '''        ["PREPARED"] = new("hand", "discard", 1, true),
        ["NEOWS_FURY"] = new("discard", "retrieve", 0, true),
        ["ARMAMENTS"] = new("hand", "upgrade", 1, false),''')
    edit(choices, '    private DiscardAudit? _discard;', '''    private DiscardAudit? _discard;
    private SamplingChoiceAudit? _samplingChoice;
    internal int SamplingChoiceLimit { get; set; }''')
    edit(choices, '        _discard = null;', '        _discard = null;\n        _samplingChoice = null;')
    edit(choices, '        if (!legal)', '''        legal &= _action switch
        {
            "NEOWS_FURY" => minSelect == 0 && SamplingChoiceLimit > 0
                && (maxSelect == SamplingChoiceLimit || maxSelect == Math.Min(SamplingChoiceLimit, cards.Length)),
            "ARMAMENTS" => SamplingChoiceLimit == 1 && minSelect == 1 && maxSelect == 1
                && cards.All(card => card.IsUpgradable),
            _ => true,
        };
        if (!legal)''')
    edit(choices, '        var indexes = ordered.Take(count).Select(v => v.Index).ToArray();',
         '''        if (_action == "NEOWS_FURY")
        {
            ordered = ordered.Where(v => v.Type is not ("Status" or "Curse")).OrderBy(v => tactical ? -Value(v) : v.Index)
                .ThenBy(v => v.Index);
            count = Math.Min(maxSelect, cards.Length);
        }
        else if (_action == "ARMAMENTS" && tactical)
            ordered = visible.OrderByDescending(Value).ThenBy(v => v.Index);
        var indexes = ordered.Take(count).Select(v => v.Index).ToArray();''')
    edit(choices, '        if (contract.Effect == "discard")',
         '''        if (_action is "NEOWS_FURY" or "ARMAMENTS")
            _samplingChoice = SamplingChoiceAudit.Capture(combat, cards, _selected);
        if (contract.Effect == "discard")''')
    edit(choices, '            bool effect = _contract!.Effect switch',
         '''            bool effect = _samplingChoice != null
                ? _samplingChoice.Verify(combat, StateChecks, _step, _action!)
                : _contract!.Effect switch''')
    edit(source / "RealCombat.cs", '        choices.Begin(request.GetProperty("step").GetInt32(), selected?.Id);',
         '''        choices.SamplingChoiceLimit = selected?.Id switch
        {
            "NEOWS_FURY" => pcs.Hand.Cards[selected.HandIndex].DynamicVars.Cards.IntValue,
            "ARMAMENTS" when pcs.Hand.Cards[selected.HandIndex].CurrentUpgradeLevel == 0 => 1,
            _ => 0,
        };
        choices.Begin(request.GetProperty("step").GetInt32(), selected?.Id);''')


if __name__ == "__main__":
    i1 = f3b.f3a.f2.f1.i1
    i1.build(i1.ROOT / "logs" / HOST, stage)
