"""Use physical option UIDs and public candidate slots for private single-choice replay."""
from build import edit

def apply(folder):
    p=folder/"HotWorld.cs"
    edit(p,"using CombatSolver.HotKernel;","using CombatSolver.HotKernel;\nusing CombatSolver.HotDraw;")
    edit(p,"int n=HotCombatEngine.EnumerateChoiceOptions(in world,cold,rules!,scratch,buffer);",
         '''int n;
        // Original Hot search may coalesce interchangeable copies. The verified
        // HotDraw enumerator preserves their individual UIDs for input binding.
        if(Probe.Current!=null)return "nested_choice_capture";
        Probe.Current=new Probe(rules!,DrawBelief.Create([],[],[]),Prefix.Empty,"private_option_slots",Resolution.Public);
        try{n=HotCombatEngine.EnumerateChoiceOptions(in world,cold,rules!,scratch,buffer);}
        finally{Probe.Current=null;}
        var candidates=menu.GetProperty("candidates");
        if(n!=candidates.GetArrayLength())return "choice_count";
        if(candidates.EnumerateArray().Any(c=>c.TryGetProperty("enchantment",out _) || c.TryGetProperty("affliction",out _)))return "choice_modifier";''')
    edit(p,'if(j==world.TotalCardCount || !options.TryAdd(CardName(rules!,world.Cards[j]),opt))return "choice_instance";',
         '''if(j==world.TotalCardCount || CardName(rules!,world.Cards[j])!=VisibleKey(candidates[i]))return "choice_slot_order";
            options.Add(i+"/"+VisibleKey(candidates[i]),opt);''')
    edit(p,'        var names=menu.GetProperty("candidates").EnumerateArray().Select(VisibleKey).ToArray();\n        if(!names.Order().SequenceEqual(options.Keys.Order()))return "choice_support_or_duplicate";','')
    edit(p,'selectedKey=VisibleKey(h.GetProperty("decision").GetProperty("candidates")[idx]);',
         'selectedKey=idx+"/"+VisibleKey(h.GetProperty("decision").GetProperty("candidates")[idx]);')
