"""Build an isolated public-draw probe and resident tactical command."""
import argparse
import hashlib
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
from time import perf_counter

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASE=ROOT/"logs/n4b-host-v2"
SV=ROOT/"logs/m1-sv4a-host"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def source_sha(p):
    return hashlib.sha256(p.read_bytes().replace(b"\r\n",b"\n")).hexdigest()

def replace(path,before,after):
    text=path.read_text(encoding="utf-8-sig")
    if text.count(before)!=1:
        raise ValueError((path,before))
    path.write_text(text.replace(before,after),encoding="utf8")


def extension(solver,sim,host):
    replay=solver/"src/Search/CombatBeamSolver.InteractiveCombat.cs"
    replace(replay,"        internal void Play(PlanAction action)","        private PileLaw? _pileOrigin;\n        internal void Play(PlanAction action)")
    replace(replay,"            _replayOrigin = Current;","            _pileOrigin=TurnDrawTape.Current?.Law.Fork();\n            _replayOrigin = Current;")
    replace(replay,"            var origin = _replayOrigin ??","            TurnDrawTape.Current?.Restore(_pileOrigin);\n            var origin = _replayOrigin ??")
    replace(replay,"            var twin = solver.Replay", "            using var twinObserver=TurnDrawTape.Diagnostic(_pileOrigin);\n            var twin = solver.Replay")
    registers=solver/"src/Search/SimulatedCombatState.MonsterAi.cs"
    replace(registers,"    public string GetPredictedMoveId",'''    internal object StrategicPhase(Creature creature)
    {
        var state=GetMonsterAiState(creature);
        var registers=new Dictionary<string,int>();
        string species=state.Monster.GetType().Name;
        if(species=="KnowledgeDemon") registers["curse_count"]=state.KnowledgeDemonCurseCounter;
        if(species=="TestSubject") registers["respawns"]=GetMonsterInt(creature,"_respawns");
        if(species=="Queen") registers["amalgam_died"]=GetMonsterBool(creature,"_hasAmalgamDied")?1:0;
        return new {node=state.Current.Id,committed_moves=state.StateLog.Where(id=>state.Machine.States.TryGetValue(id,out var n) && n.IsMove).ToArray(),
            registers,rule_ref=creature.Monster?.Id.Entry};
    }
    public string GetPredictedMoveId''')
    turn=solver/"src/Search/CombatBeamSolver.TurnExecutionContinuation.cs"
    replace(turn,"            progress.DrawHistoryStart = simulator.History.Entries.Count;",
            "            if (!progress.RootSetup && !simulator.IsOverOrEnding) TurnDrawTape.Current?.AtC?.Invoke(simulator,player,progress.TurnNumber,progress.DrawCount,progress.WillShuffle,progress.SideStarted,progress.TakingExtraTurn);\n            progress.DrawHistoryStart = simulator.History.Entries.Count;")
    pile=sim/"CombatPredictionSimulator.CardPile.cs"
    replace(pile,"        AddToPile(shuffledCards, state.DrawPile);",
            "        var observer=TurnDrawTape.Current;\n        if(observer!=null) observer.SuppressMoves=true;\n        try { AddToPile(shuffledCards, state.DrawPile); } finally { if(observer!=null) observer.SuppressMoves=false; }")
    replace(pile,"        oldPile?.Remove(card);","        TurnDrawTape.Move(card,oldPileType,targetPile.Type,position);\n        oldPile?.Remove(card);")
    replace(pile,"            card.GetPile(playerCombatState)?.Remove(card);",
            "            TurnDrawTape.Move(card,result.OldPileType,targetPile.Type,position);\n            card.GetPile(playerCombatState)?.Remove(card);")
    replace(pile,"            results.Add(AddToPile(card, newPileType, position));",
            "            var observer=TurnDrawTape.Current;\n            if(observer!=null) observer.KnownGeneration=resultKind==CardGenerationResultKind.Fixed;\n            try { results.Add(AddToPile(card, newPileType, position)); } finally { if(observer!=null) observer.KnownGeneration=false; }")
    replace(pile,"            SearchProbe.BeforeDraw(this,", "            if(TurnDrawTape.Current is {} observing) observing.Drawing=true;\n            SearchProbe.BeforeDraw(this,")
    replace(pile,"        pile.Remove(card);\n        card.MutablePreview.HasBeenRemovedFromState", "        TurnDrawTape.Removed(pile.Type);\n        pile.Remove(card);\n        card.MutablePreview.HasBeenRemovedFromState")
    replace(pile,"            pile.Remove(card);\n            removedCards.Add", "            TurnDrawTape.Removed(pile.Type);\n            pile.Remove(card);\n            removedCards.Add")
    text=pile.read_text(encoding="utf8")
    old="CardPilePosition.Random => Rng.Shuffle.NextInt(targetPile.Cards.Count + 1)"
    assert text.count(old)==2
    pile.write_text(text.replace(old,"CardPilePosition.Random when targetPile.Type==PileType.Discard && SearchProbe.IsPlanning => targetPile.Cards.Count,\n            CardPilePosition.Random when targetPile.Type==PileType.Draw => TurnDrawTape.Insertion(()=>Rng.Shuffle.NextInt(targetPile.Cards.Count + 1),targetPile.Cards.Count),\n            "+old),encoding="utf8")
    enemy=solver/"src/Prediction/MonsterRandomBranchResolver.cs"
    replace(enemy,'            CombatSolver.Engine.InCombat.Simulation.SearchProbe.Stop("monster_multi_outcome_rng");',
            '''        {
            var legal=weighted.Where(x=>x.Weight>0).OrderByDescending(x=>x.Weight).ThenBy(x=>x.State.stateId,StringComparer.Ordinal).ToArray();
            var observer=CombatSolver.Engine.InCombat.Simulation.TurnDrawTape.Current;
            if(CombatSolver.Engine.InCombat.Simulation.SearchProbe.IsPlanning && legal.Length==1) return legal[0].State.stateId;
            if(observer?.ModelEnemy==true && legal.Length>1) {
                observer.EnemyModels.Add(new {branch=branch.Id,chosen=legal[0].State.stateId,eligible=legal.Select(x=>x.State.stateId).ToArray()});
                return legal[0].State.stateId;
            }
            CombatSolver.Engine.InCombat.Simulation.SearchProbe.Stop("enemy_condition_unidentified");
        }''')
    knowledge=host/"KnowledgeChoice.cs"
    replace(knowledge,"        var type = _interactive!.GetType();",
            "        SubmitKnowledgeChoice(request,index,_interactive!);\n    }\n    private void SubmitKnowledgeChoice(KnowledgeDemonChoiceRequest request,int index,object receiver)\n    {\n        var type = receiver.GetType();")
    for before,after in [("field.GetValue(_interactive)","field.GetValue(receiver)"),
                         ("field.SetValue(_interactive,", "field.SetValue(receiver,"),
                         ('InteractiveInvoke("Install", resumed);','type.GetMethod("Install", PrivateInstance)!.Invoke(receiver,[resumed]);')]:
        replace(knowledge,before,after)
    source=knowledge.read_text(encoding="utf8")
    assert source.count("Invoke(_interactive, null)")==2
    knowledge.write_text(source.replace("Invoke(_interactive, null)","Invoke(receiver, null)"),encoding="utf8")
    episode=host/"InteractiveEpisode.cs"
    replace(episode,".Invoke(solver, [_root.State]);",".Invoke(solver, [_root.State]);\n        InitializeLaw();")
    replace(episode,"        bool waiting = InteractiveProperty<bool>(\"Waiting\");",
            "        using var publicEvents=Observer(_law,[],false,false).Enter();\n        _observedC=null;\n        bool waiting = InteractiveProperty<bool>(\"Waiting\");")
    replace(episode,"            _decisionPosition++;","            _law=publicEvents.Law;\n            _observedC=publicEvents.Strategic;\n            _lastEvents=publicEvents.Events.ToArray();\n            _decisionPosition++;")
    replace(episode,"            status, observation, automatic","            status, observation, public_law=_law.Export(), observed_c=_observedC, pile_events=_lastEvents, automatic")


def build(out,prior=None):
    t=perf_counter()
    identity=json.loads((BASE/"build.json").read_bytes())
    for p,h in identity["artifacts"].items():
        assert sha(BASE/p)==h
    assert sha(SV/"solver-bin/CombatSolver.dll")==identity["artifacts"]["solver-bin/CombatSolver.dll"]
    out.mkdir(parents=True,exist_ok=False)
    solver=out/"solver"
    shutil.copytree(SV/"solver/src",solver/"src")
    shutil.copyfile(SV/"solver/CombatSolver.csproj",solver/"CombatSolver.csproj")
    sim=solver/"src/Engine/InCombat/Simulation"
    probe=sim/"SearchProbe.cs"
    replace(probe,"internal sealed class SearchProbe","internal sealed partial class SearchProbe")
    replace(probe,"        probe.Draw ??= new","        if (probe.TurnDraw != null) { TurnDrawTape.Current!.Draw(sim, player, remaining); return; }\n        probe.Draw ??= new")
    shutil.copyfile(HERE/"PublicDraw.cs",sim/"PublicDraw.cs")
    replace(sim/"CombatPredictionSimulator.CardPile.cs","        shuffledCards.StableShuffle(Rng.Shuffle, this);",
            "        if (!SearchProbe.PublicShuffle(this, player, shuffledCards))\n            shuffledCards.StableShuffle(Rng.Shuffle, this);")
    replay=solver/"src/Search/CombatBeamSolver.Expansion.Replay.cs"
    replace(replay,"    private SimulationSnapshot Replay(","    internal SimulationSnapshot TacticalFork(SimulationSnapshot s) => Replay([], s, s.Turn);\n\n    private SimulationSnapshot Replay(")
    shutil.copytree(BASE/"host",out/"host",ignore=shutil.ignore_patterns("obj","bin"))
    host=out/"host/Headless"
    project=host/"Sts2Headless.csproj"
    replace(project,str(SV/"solver-bin/CombatSolver.dll"),str(out/"solver-bin/CombatSolver.dll"))
    replace(host/"IntegrationProbe.cs",'        if (command == "i1_sv1_graph")',
            '        if (command == "i1_core1r2")\n            return (_episode ?? throw new InvalidOperationException("Reset first")).Tactical(cmd);\n        if (command == "i1_sv1_graph")')
    shutil.copyfile(HERE/"Tactical.cs",host/"Tactical.cs")
    replace(host/"NoslPublicEpisode.cs","nunchaku = PublicNunchakuCount(sim),",
            'nunchaku = PublicNunchakuCount(sim),\n            tuning_fork = combat.RelicsOf(_player)'
            '.Where(r => r.Id.Entry == "TUNING_FORK").Select(r => (int?)(combat.ReadRelicCounter(sim,r)'
            ' % r.DynamicVars.Cards.IntValue)).SingleOrDefault(),\n'
            '            order_hooks = combat.EffectivePowers().Where(p => p.IsVisible && '
            '(p.Owner == _player.Creature || targets.Contains(p.Owner))).Select(p => new '
            '{ owner = Array.IndexOf(targets,p.Owner), id = p.Id.Entry }).OrderBy(p => p.owner)'
            '.ThenBy(p => p.id,StringComparer.Ordinal).ToArray(),')
    shutil.copyfile(HERE/"Strategic.cs",host/"Strategic.cs")
    catalog=HERE.parent/"m1-n1bc/catalog.json.gz"
    cards=json.loads(gzip.decompress(catalog.read_bytes()))["cards"]
    rules=[f'[{json.dumps(id)}]=[{",".join(json.dumps(op[0]) for op in entry["operations"])}]'
           for id,entry in sorted(cards.items()) if entry["operations"]]
    replace(host/"Tactical.cs","/* compiled public operations */",",\n".join(rules))
    identity["sources"]["n1bc_catalog"]=sha(catalog)
    extension(solver,sim,host)
    env=os.environ|dict(DOTNET_CLI_HOME=str(out),NUGET_PACKAGES=str(ROOT/"logs/nuget-packages"))
    steam=Path.home()/"Desktop/STEAM/steamapps"
    if prior:
        source=json.loads((prior/"build.json").read_bytes())
        assert source["sources"]["PublicDraw.cs"]==source_sha(HERE/"PublicDraw.cs")
        assert source["artifacts"]["solver-bin/CombatSolver.dll"]==sha(prior/"solver-bin/CombatSolver.dll")
        for path in (solver/"src").rglob("*.cs"):
            assert source_sha(path)==source_sha(prior/"solver"/path.relative_to(solver))
        shutil.copytree(prior/"solver-bin",out/"solver-bin")
    with (out/"build.log").open("w",encoding="utf8") as log:
        for args in ([str(solver/"CombatSolver.csproj"),"-c","Release","-p:CopyModOnBuild=false","-p:OS=Unix",
                      f"-p:Sts2DataDir={steam/'common/Slay the Spire 2/data_sts2_windows_x86_64'}",
                      f"-p:RitsuWorkshopRoot={steam/'workshop/content/2868840/3747602295'}",
                      "-o",str(out/"solver-bin")],[str(project)]):
            if prior and args[0]!=str(project): continue
            subprocess.run(["dotnet","build",*args,"-p:NuGetAudit=false","--verbosity","quiet"],env=env,
                           stdout=log,stderr=subprocess.STDOUT,timeout=240,check=True)
    identity["artifacts"]={p:sha(out/p) for p in identity["artifacts"]}
    identity["sources"].update({p.name:source_sha(p) for p in HERE.glob("*.cs")})
    identity["build_seconds"]=perf_counter()-t
    (out/"build.json").write_text(json.dumps(identity,indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("out",type=Path)
    p.add_argument("--solver-build",type=Path)
    a=p.parse_args()
    build(a.out.resolve(),a.solver_build)
