"""Isolated diagnostic host. Resample only an exchangeable hidden tail at the live public root."""
from build5b import build,build_state,extend
from pathlib import Path
import json,sys

def extension(solver,sim,host):
    extend(solver,sim,host)
    # Opt-in comparison: let a single card expose its third draw while retaining
    # the original frontier, key-card heuristic, pending-choice and settlement rules.
    build.replace(host/"Tactical.cs","tape.Length>=2?Stop", 'tape.Length>=(request.TryGetProperty("review_third_draw",out var third) && third.GetBoolean()?3:2)?Stop')
    add_world_sampler(host)

def add_world_sampler(host):
    build.replace(host/"Reference.cs",'if(request.TryGetProperty("clear",out _))','''if(request.TryGetProperty("diagnostic_world",out var world)){
            ClearReference();
            var pile=source.Simulator.State.GetPlayerCombatState(_player).DrawPile;
            if(_law.Top.Count+_law.Bottom.Count!=0 || _law.Missing!=null || _law.OrderMissing!=null || _law.ShuffleModifier)
                throw new InvalidOperationException("Expected an exchangeable tail");
            var ordered=pile.Cards.OrderBy(c=>CardChoiceSupport.ChoiceCardKey(c),StringComparer.Ordinal).ToArray();
            var groups=ordered.GroupBy(TurnDrawTape.Type).ToArray();
            if(groups.Length!=_law.Counts.Count || groups.Any(g=>g.Count()!=_law.Counts.GetValueOrDefault(g.Key)
                || g.Select(CardChoiceSupport.ChoiceCardKey).Distinct().Count()!=1))
                throw new InvalidOperationException("Tail or instance law mismatch");
            var rng=new System.Random(world.GetInt32());
            for(int i=ordered.Length-1;i>0;i--){int j=rng.Next(i+1);(ordered[i],ordered[j])=(ordered[j],ordered[i]);}
            pile.Clear();
            foreach(var c in ordered)pile.Add(c);
            return new {kind="sampled",law=_law.Export(),state=ObserveNosl(_root,source)};
        }
        if(request.TryGetProperty("clear",out _))''')

if __name__=="__main__":
    out=Path(sys.argv[1]).resolve()
    build.extension=extension;build.build(out)
    (out/"build.json").write_text(json.dumps(build_state.manifest(out),indent=2))
