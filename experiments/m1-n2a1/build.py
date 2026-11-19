"""Stage N2A.1 without editing the frozen N2A worker."""
from pathlib import Path
import runpy
import shutil

HERE = Path(__file__).resolve().parent
base = runpy.run_path(str(HERE.parent / "m1-n2a/build.py"))
s3a = base["s3a"]


def stage(src):
    base["stage"](src)
    shutil.copyfile(HERE / "PublicInteraction.cs", src / "PublicInteraction.cs")
    edit = s3a.edit
    episode = src / "Episode.cs"
    edit(episode, 'int Hp, int Block);', 'int Hp, int Block, ImmutableArray<int> AttackHits, ImmutableArray<string> Intents, ImmutableArray<PublicPower> Powers);')
    edit(episode, 'int? Target, int? Cost);',
         'int? Target, int? Cost, PublicCard? Choice = null, Preview? Preview = null);')
    edit(episode, '                actions.Add(new(actions.Count, index, targetIndex, cost));\n                moves.Add(new(new PlanAction',
         '                var plan = new PlanAction')
    edit(episode, 'CardStateOccurrence: previous.Count(c => CardChoiceSupport.ChoiceCardKey(c) == key)), null));',
         '''CardStateOccurrence: previous.Count(c => CardChoiceSupport.ChoiceCardKey(c) == key));
                var preview = ImmediatePreview(sim, card, targetIndex is int slot ? targets[slot] : null);
                foreach (var (publicChoice, token) in PublicChoices(sim, card))
                {
                    actions.Add(new(actions.Count, index, targetIndex, cost, publicChoice, preview));
                    moves.Add(new(plan with { Choice = token }, null));
                }''')
    edit(episode, 'sim.State.GetCreature(e).Block)).ToImmutableArray(),',
         'sim.State.GetCreature(e).Block, CurrentAttackHits(sim, combat, e), CurrentIntents(combat, e), PublicPowers(combat, e))).ToImmutableArray(),')
    edit(episode, 'ImmutableArray<PublicAction> Actions);',
         'ImmutableArray<PublicAction> Actions, ImmutableArray<PublicPower> Powers);')
    edit(episode, '            actions.ToImmutable());',
         '            actions.ToImmutable(), PublicPowers(combat, _player.Creature));')
    edit(episode, '            status, observation, detail = _episodeDetail,',
         '''            status, observation, detail = _episodeDetail,
            audit_action = node.Option?.Action, audit_stamp = node.Frame.Stamp,''')
    # Return typed command rejection without mutating a valid episode.
    edit(episode, 'throw new InvalidOperationException("Episode has no active legal menu");',
         'return InvalidAction("Episode has no active legal menu");')
    edit(episode, 'throw new ArgumentException("Stale action position");',
         'return InvalidAction("Stale action position");')
    edit(episode, 'throw new ArgumentException("Action index outside current menu");',
         'return InvalidAction("Action index outside current menu");')


if __name__ == "__main__":
    i1 = s3a.b1b.b1a.i1
    i1.build(i1.ROOT / "logs/m1-n2a1-build", stage)
