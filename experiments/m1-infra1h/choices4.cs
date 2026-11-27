    // The action is replayed from this value parent only after CORE has confirmed
    // a single legal player selection. Partial execution never reaches a policy.
    private sealed record Pending(CombatHotState Parent,HotColdSidecar? Cold,HotAction Action,Dictionary<string,HotChoiceSelection> Options);
    private static Pending? pending;
    private static string? selectedKey;
    private static string VisibleKey(JsonElement card)=>card.GetProperty("id").GetString()+"#"+card.GetProperty("upgrade").GetInt32();
    private static string? CaptureChoice(CombatHotState parent,HotColdSidecar? parentCold,HotAction action,JsonElement after)
    {
        if(scratch.PendingChoiceMin!=1 || scratch.PendingChoiceMax!=1 ||
           scratch.PendingChoiceKind is not (HotChoiceKind.HandCard or HotChoiceKind.DiscardPile or HotChoiceKind.ExhaustPile))
            return "choice_scope/"+scratch.PendingChoiceKind;
        if(!after.TryGetProperty("observation",out var h))return "missing_choice";
        var menu=h.GetProperty("decision");
        if(menu.GetProperty("phase").GetString()!="choice" || menu.GetProperty("max").GetInt32()!=1 || menu.GetProperty("min").GetInt32()!=1)return "choice_phase";
        Span<HotChoiceSelection> buffer=stackalloc HotChoiceSelection[HotLimits.MaxCards+1];
        int n=HotCombatEngine.EnumerateChoiceOptions(in world,cold,rules!,scratch,buffer);
        var options=new Dictionary<string,HotChoiceSelection>(StringComparer.Ordinal);
        for(int i=0;i<n;i++){
            var opt=buffer[i];
            int j=0;
            while(j<world.TotalCardCount && world.Cards[j].CardUid!=opt.CardUidOrIndex)j++;
            if(j==world.TotalCardCount || !options.TryAdd(CardName(rules!,world.Cards[j]),opt))return "choice_instance";
        }
        var names=menu.GetProperty("candidates").EnumerateArray().Select(VisibleKey).ToArray();
        if(!names.Order().SequenceEqual(options.Keys.Order()))return "choice_support_or_duplicate";
        pending=new(parent,parentCold,action,options);selectedKey=null;
        return null;
    }
