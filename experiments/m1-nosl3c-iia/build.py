"""Build the isolated II-A host without changing frozen experiment hosts."""
from pathlib import Path
import runpy
import shutil

HERE = Path(__file__).resolve().parent
BASE = runpy.run_path(str(HERE.parent / "m1-nosl3c/build.py"))
BINDING = BASE["BASE"]["N2A"]["s3a"]
HOST = "m1-nosl3c-iia-build"


def stage(src):
    BASE["stage"](src)
    shutil.copyfile(HERE / "PublicEpisode.cs", src / "NoslPublicEpisode.cs")
    edit = BINDING.edit
    combat = src / "SyntheticCombat.cs"
    edit(combat, 'spec.Schema is not (1 or 2)', 'spec.Schema is not (1 or 2 or 3)')
    edit(combat, 'spec.Act is not (1 or 2)', 'spec.Act < 1 || spec.Act > (spec.Schema == 3 ? 3 : 2)')
    edit(combat, '|| spec.Schema == 2 && (spec.ActVariant', '''|| spec.Schema == 3 && (spec.ActVariant is null ||
                spec.Relics is not { Length: 0 } || spec.Potions is null || spec.Potions.Any(p => p != null))
            || spec.Schema == 2 && (spec.ActVariant''')
    edit(combat, 'Length: >= 1 and <= 40', 'Length: >= 1')
    edit(combat, '|| spec.Deck is not { Length: >= 1 }', '''|| spec.Deck is not { Length: >= 1 }
            || spec.Schema != 3 && spec.Deck.Length > 40''')
    edit(combat, 'spec.Schema == 2 && !pool.Contains', 'spec.Schema >= 2 && !pool.Contains')
    catalog = src / "SyntheticCatalog.cs"
    edit(catalog, '"Ironclad", "Silent"', '"Ironclad", "Silent", "Defect", "Regent", "Necrobinder"')


if __name__ == "__main__":
    i1 = BINDING.b1b.b1a.i1
    i1.build(i1.ROOT / "logs" / HOST, stage)
