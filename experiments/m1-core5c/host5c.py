"""Build the opt-in shared public transition kernel on the frozen 5B host overlay."""
import sys,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"m1-core5b"))
import build5b
from build5b import build,build_state
def extend(solver,sim,host):
    build5b.extend(solver,sim,host)
    replace=build.replace
    ref=host/"Reference.cs"
    replace(ref,'var edges=request.GetProperty', '''bool complete=request.TryGetProperty("complete",out var flag) && flag.GetBoolean();
        var edges=request.GetProperty''')
    replace(ref,'int start=edges.Length;', '''if(complete) for(int i=0;i<keys.Length;i++) keys[i]="C"+keys[i];
        int start=edges.Length;''')
    replace(ref,'tape.ReferenceEvents=true;','tape.ReferenceEvents=true; tape.Complete=complete;')
    replace(ref,'support=tape.Options,calls','support=tape.Options,batch=tape.Batch,calls')
    replace(ref,'referencePrefixes[keys[^1]]=(_pre0bSolver.TacticalFork(current),law.Fork());','''{
                    if(referencePrefixes.Count>=48){
                        string oldest=referencePrefixes.Keys.First();
                        referencePrefixes[oldest].Snapshot.ReleaseSimulator();
                        referencePrefixes.Remove(oldest);
                    }
                    referencePrefixes[keys[^1]]=(_pre0bSolver.TacticalFork(current),law.Fork());
                }''')
    tape=sim/"PublicDraw.cs"
    replace(tape,'internal bool ReferenceEvents;', 'internal bool ReferenceEvents,Complete; internal int Batch=1;')
    replace(tape,'if(Used==prefix.Length)\n        {\n            var v=', '''bool certain=Complete && Options.Count==1;
        if(!certain && Used==prefix.Length)
        {
            if(Complete && Law.Top.Count==0 && Law.Missing==null && Law.OrderMissing==null)
                Batch=Math.Min(Math.Min(remaining,Options.Values.Sum()),sim.GetMaxHandSize(player)-pc.Hand.Cards.Count);
            var v=''')
    replace(tape,'var key=prefix[Used++];\n        if(!Options','var key=certain?Options.Keys.Single():prefix[Used++];\n        if(!Options')
    # Uniform sampling without replacement from the same filtered, unlocked card pool.
    ext=solver/"src/Engine/InCombat/Extensions/CombatCardGenerationExtensions.cs"
    text=ext.read_text(encoding="utf-8-sig").replace(".TakeRandom(count, rng)",".PublicDistinct(count, rng)")
    ext.write_text(text,encoding="utf8")
    replace(ext,'    public static IEnumerable<CardModel> FilterForCombatAndPlayerCount', '''    private static IEnumerable<CardModel> PublicDistinct(this IEnumerable<CardModel> cards,int count,Rng rng){
        if(TurnDrawTape.Current is not {Complete:true} tape) return cards.TakeRandom(count,rng);
        var available=cards.ToList(); var result=new List<CardModel>();
        while(result.Count<count && available.Count>0){
            var picked=tape.Uniform(available,"generate")!;
            result.Add(picked);available.Remove(picked);
        }
        return result;
    }
    public static IEnumerable<CardModel> FilterForCombatAndPlayerCount''')
    mirrors=solver/"src/Engine/InCombat/Mirrors/Cards/OnPlay"
    p=mirrors/"CardGenerationCardMirrors.cs"
    replace(p,'GetDistinctUnlockedCharacterAttacksForCombat(\n                card.Owner,\n                1,\n                context.Rng.CombatCardGeneration,','GetDistinctUnlockedCharacterAttacksForCombat(\n                card.Owner,\n                1,\n                TurnDrawTape.Current is {Complete:true}?null!:context.Rng.CombatCardGeneration,')
    p=mirrors/"CardSelectionCardMirrors.cs"
    replace(p,'''var selectedCard = context.Rng.CombatCardSelection.NextItem(
            preferredCards.Count == 0 ? eligibleCards : preferredCards);''','''var pool=preferredCards.Count==0?eligibleCards:preferredCards;
        var selectedCard=TurnDrawTape.Current is {Complete:true} tape?tape.Uniform(pool,"hand"):context.Rng.CombatCardSelection.NextItem(pool);''')
if __name__=="__main__":
    out=Path(sys.argv[1]).resolve()
    build.extension=extend;build.build(out)
    (out/"build.json").write_text(json.dumps(build_state.manifest(out),indent=2))
