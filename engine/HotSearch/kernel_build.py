"""Apply the HotDraw event additions in a new tree, leaving the frozen solver untouched."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import zipfile


def kernel(here,root,build):
    base=root/"experiments/hotdraw/build.py"
    module=importlib.util.spec_from_file_location("frozen_draw_build",base)
    hd=importlib.util.module_from_spec(module);module.loader.exec_module(hd)
    archive=root.parent/"hk0-isolated-131d10a/upstream.zip"
    if hd.checksum(archive)!=hd.ARCHIVE_SHA:raise ValueError("upstream archive identity")
    tree=build/"rules"/("CombatSolver-"+hd.PIN)
    binary=tree/".godot/mono/temp/bin/Release/CombatSolver.dll"
    key=hashlib.sha256(b"".join(p.read_bytes() for p in [Path(__file__),here/"kernel/Events.cs",
        base,*sorted(base.parent.glob("*.cs")),root/"experiments/m1-infra1h/InfraCObserver.cs"])).hexdigest()
    stamp=build/"rules.sha256"
    if stamp.exists() and binary.exists() and stamp.read_text()==key+" "+hd.checksum(binary):return binary
    with zipfile.ZipFile(archive) as z:z.extractall(tree.parent)
    hd.instrument(tree)
    hk=tree/"src/HotKernel"
    sim=hk/"Sim"
    edit=hd.edit
    play=sim/"HotCombatEngine.CardPlay.cs"
    turn=sim/"HotCombatEngine.Turn.cs"
    anchor="            DrawCards(ref s, ref cold, rules, scratch, drawCount, fromHandDraw: true);"
    edit(turn,anchor,"            InfraCObserver.BeforeDraw?.Invoke(in s,cold,rules,drawCount);\n"+anchor)
    shutil.copyfile(root/"experiments/m1-infra1h/InfraCObserver.cs",sim/"InfraCObserver.cs")
    edit(play,"private static HotCard CreateFreshCard(","internal static HotCard CreateFreshCard(")
    probe="global::CombatSolver.HotDraw.Probe.Current"
    edit(play,probe+'?.Reject("autoplay_from_draw", nameof(AutoPlayFromDrawPile));',"")
    edit(play,"            if (upgradeBeforePlay)",f'            {probe}?.Autoplay(ref s,cold,scratch,cap-i);\n            if (upgradeBeforePlay)')
    # Copy on each resolved play (including autoplay and repeats), before the original leaves Play.
    anchor="            bool playedWasEthereal = curPlayIdx >= 0"
    edit(play,anchor,'''            if (cardDef.Entry=="OUTRAGE" && !IsOverOrEnding(in s)) {
                if(curPlayIdx<0)throw new NotSupportedException("OUTRAGE/source");
                var src=s.Cards[curPlayIdx];
                if(src.AfflId!=0 || src.EnchId!=0 || src.CostModCount!=0)
                    throw new NotSupportedException("OUTRAGE/modified");
                var copy=CreateFreshCard(ref s,cardDef,src.UpgradeLevel!=0);
                AddGeneratedCardInstance(ref s,ref cold,rules,scratch,in copy,HotPileKind.Discard,-1,true);
            }
'''+anchor)
    edit(sim/"HotPiles.cs",probe+'?.Reject("generated_instance", nameof(AddCard));',
         probe+"?.Added(in s,in card,dstPile,dstOffsetInPile);")
    anchor="actualOffset = HotRng.NextInt(ref s.Rng[(int)HotRngStream.Shuffle], zoneCount + 1);"
    edit(play,anchor,f"actualOffset = actualPile==HotPileKind.Draw && {probe}?.BeginRandomInsert()==true ? zoneCount : "+anchor.split(" = ")[1])
    resolver=hk/"Resolver.cs"
    law=hk/"Belief.cs"
    edit(law,"    public static DrawBelief Create","    internal Dictionary<string,int>? Counts { get; init; }\n    public static DrawBelief Create")
    edit(resolver,"Belief = Belief.Draw(selected);","Belief = Belief.Draw(selected);\n        Count(state.Cards[state.DrawStart],-1);")
    edit(resolver,"Belief = Belief.Shuffle(ids);","Belief = Belief.Shuffle(ids);\n            ResetMembership(in state);")
    edit(resolver,"internal sealed class Probe(","internal sealed partial class Probe(")
    edit(resolver,"Shuffle, PlayerChoice","Shuffle, PlayerChoice, Monster")
    edit(resolver,"public double Probability => 1.0 / Denominator;","public double? Weight {get;init;}\n    public double Probability => Weight ?? (1.0 / Denominator);")
    edit(resolver,"HotChoiceKind Kind, ushort Instance);","HotChoiceKind Kind, ushort Instance, ushort Def = 0);")
    edit(resolver,"or HotChoiceKind.ExhaustPile))","or HotChoiceKind.ExhaustPile or HotChoiceKind.GeneratedCard))")
    edit(resolver,"buffer[i].CardUidOrIndex);","buffer[i].CardUidOrIndex, buffer[i].CardDefId);")
    edit(resolver,"if (source == HotPileKind.Draw)","if (source == HotPileKind.Draw && !ConsumeStaged(state.Cards[index].CardUid,destination))")
    edit(resolver,"Belief = Belief.Insert(state.Cards[index].CardUid", "Count(state.Cards[index],1); Published?.Invoke(state.Cards[index]);\n            Belief = Belief.Insert(state.Cards[index].CardUid")
    for file in (sim/"HotCombatEngine.Monsters.cs",sim/"Content/HotMonsters.cs"):
        anchor="float roll = HotRng.NextFloat(ref rng, total);"
        edit(file,anchor,f'if ({probe} is {{PublicMode:true}} observer)\n            return branch.BranchTargets[observer.MonsterChoice(weights,total,machine.MonsterEntry+"/"+enemySlot+"/"+branch.MoveId)];\n        '+anchor)
    for name in ("AdjustMonsterMoveDamage","ResolveAttackRepeats","ComputeRepeatWeight"):
        typ="float" if name=="ComputeRepeatWeight" else "int"
        edit(sim/"Content/HotMonsters.cs",f"private static {typ} {name}(",f"internal static {typ} {name}(")
    edit(sim/"HotCombatEngine.Damage.cs","private static decimal ComputeModifiedDamage(","internal static decimal ComputeModifiedDamage(")
    edit(resolver,"ids[i] = cards[i].CardUid;","Published?.Invoke(cards[i]);\n                ids[i] = cards[i].CardUid;")
    shutil.copyfile(here/"kernel/Events.cs",hk/"HotEvents.cs")
    foundation=root/"logs/infra1h-hot-k2"
    shutil.copyfile(next(foundation.glob("CombatSolver-*/NuGet.Config")),tree/"NuGet.Config")
    data=build/"game-refs"
    data.mkdir(exist_ok=True)
    for p in (root/"lib").glob("*.dll"):shutil.copyfile(p,data/p.name)
    shutil.copyfile(root/"logs/infra1h-5d-base2/host/Headless/bin/Debug/net9.0/GodotSharp.dll",data/"GodotSharp.dll")
    steam=Path(os.environ.get("STS2_STEAM",str(Path.home()/"Desktop/STEAM")))
    env=os.environ|dict(NUGET_PACKAGES=str(foundation/"packages"),DOTNET_CLI_HOME=str(build/"cli"),DOTNET_NOLOGO="1")
    subprocess.run(["dotnet","build",str(tree/"CombatSolver.csproj"),"-c","Release","-m:1","-v:q","-p:CopyModOnBuild=false",
        "-p:NuGetAudit=false","-p:SteamRoot="+str(steam),"-p:Sts2DataDir="+str(data)],cwd=tree,env=env,check=True)
    stamp.write_text(key+" "+hd.checksum(binary))
    return binary
