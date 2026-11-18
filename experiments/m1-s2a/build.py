"""Stage the S1 host with a native catalog and explicit synthetic act selection."""
import importlib.util
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("s2a_s1_build", HERE.parent / "m1-s1/build.py")
s1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s1)
HOST = "m1-s2a-build"


def stage(src):
    s1.stage(src)
    shutil.copyfile(HERE / "SyntheticCatalog.cs", src / "SyntheticCatalog.cs")
    edit = s1.f3b.f3a.f2.replace
    edit(src / "Program.cs", '                if (kind == "synthetic_start")',
         '''                if (kind == "synthetic_catalog")
                    result = sim.SyntheticCatalog();
                else if (kind == "synthetic_start")''')
    combat = src / "SyntheticCombat.cs"
    edit(combat, 'string[] Relics, string?[] Potions);',
         'string[] Relics, string?[] Potions, int Act = 1, string? ActVariant = null);')
    edit(combat, 'spec.Schema != 1', '''spec.Schema is not (1 or 2)
            || spec.Act is not (1 or 2)
            || spec.Schema == 2 && (spec.ActVariant is null || spec.Character is not ("Ironclad" or "Silent"))
            || spec.Schema == 1 && (spec.Act != 1 || spec.ActVariant is not null)''')
    edit(combat, 'if (spec.Relics.Any(r => r is not "BURNING_BLOOD")',
         '''var player = CreatePlayer(spec.Character) ?? throw new ArgumentException("Unknown character");
        if (spec.Relics.Any(r => !player.Relics.Any(native => native.Id.Entry == r))''')
    edit(combat, 'null or "FLEX_POTION"', 'null or "FLEX_POTION" or "DEXTERITY_POTION"')
    edit(combat, '''        var player = CreatePlayer(spec.Character) ?? throw new ArgumentException("Unknown character");
        var encounter''', '        var encounter')
    edit(combat, '''        if (encounter.RoomType != RoomType.Monster || !acts[0].AllEncounters.Any(e => e.Id == encounter.Id))
            return Error("Synthetic combat supports ordinary encounters from the default first act");''',
         '''        int actIndex = spec.Act - 1;
        if (spec.ActVariant is string variant)
        {
            var model = ModelDb.ActsByIndex[actIndex].SingleOrDefault(a => a.Id.Entry == variant);
            if (model is null)
                return Error("Unknown act variant for the requested act");
            acts[actIndex] = model.ToMutable();
        }
        if (encounter.RoomType != RoomType.Monster || !acts[actIndex].AllEncounters.Any(e => e.Id == encounter.Id))
            return Error("Encounter must be an ordinary member of the selected act variant");
        var pool = player.Character.CardPool.AllCards.Concat(player.Character.StartingDeck)
            .Select(c => c.Id.Entry).ToHashSet(StringComparer.Ordinal);''')
    edit(combat, '''            return (model: ModelDb.GetById<CardModel>(new ModelId("CARD", c.Id)), c.Upgrade);''',
         '''            if (spec.Schema == 2 && !pool.Contains(c.Id))
                throw new ArgumentException($"Card {c.Id} is outside the native character pool");
            var model = ModelDb.GetById<CardModel>(new ModelId("CARD", c.Id));
            if (c.Upgrade == 1 && !model.IsUpgradable)
                throw new ArgumentException($"Cannot upgrade {c.Id}");
            return (model, c.Upgrade);''')
    edit(combat, '        manager.SetUpNewSingleplayer(_runState, shouldSave: false);',
         '''        manager.SetUpNewSingleplayer(_runState, shouldSave: false);
        // Setup generates the selected variants' native room sets. EnterRoomDebug reads the active act.
        _runState.CurrentActIndex = actIndex;
        if (_runState.Act.Id != acts[actIndex].Id || _runState.Act.BossEncounter is null)
            return Error("Requested act did not receive a native room set");''')
    edit(combat, '            ["ascension"] = run.AscensionLevel,',
         '''            ["ascension"] = run.AscensionLevel,
            ["act"] = run.CurrentActIndex + 1,
            ["act_variant"] = run.Act.Id.Entry,
            ["act_boss"] = run.Act.BossEncounter?.Id.Entry,''')


if __name__ == "__main__":
    i1 = s1.f3b.f3a.f2.f1.i1
    i1.build(i1.ROOT / "logs" / HOST, stage)
