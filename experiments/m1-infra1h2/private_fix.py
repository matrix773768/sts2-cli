"""Apply verified option binding and the OUTRAGE discard-copy rule to the K6 actual lane."""
def install(plugin):
    from build import edit
    path=plugin/"HotWorld.cs"
    edit(path,'return "early_terminal";','return "early_terminal/"+world.TerminalOutcome+"/"+world.Player.CurrentHp;')
    edit(path,'return key;\n        foreach(var (key,pile)','return key+"/"+value+"/"+h.GetProperty(key).GetInt32();\n        foreach(var (key,pile)')
    edit(path,'return "choice_phase";','return "choice_phase/"+scratch.PendingChoiceKind+"/"+scratch.PendingChoiceMin+"/"+scratch.PendingChoiceMax;')
    edit(path,"HotAction Action,Dictionary<string,HotChoiceSelection> Options","HotAction Action,HotChoiceSelection[] Prefix,Dictionary<string,HotChoiceSelection> Options")
    edit(path,"HotAction action,JsonElement after)","HotAction action,HotChoiceSelection[] prefix,JsonElement after)")
    edit(path,"pending=new(parent,parentCold,action,options)","pending=new(parent,parentCold,action,prefix,options)")
    edit(path,"selected=[binding]","selected=[..choice.Prefix,binding]")
    edit(path,"CaptureChoice(parent,parentCold,play,after)","CaptureChoice(parent,parentCold,play,selected,after)")
    edit(path,"or HotChoiceKind.ExhaustPile))","or HotChoiceKind.ExhaustPile or HotChoiceKind.GeneratedCard))")
    edit(path,'if(candidates.EnumerateArray().Any(c=>c.TryGetProperty("enchantment",out _) || c.TryGetProperty("affliction",out _)))return "choice_modifier";','')
    edit(path,"int j=0;",'''if(opt.Kind==HotChoiceKind.GeneratedCard){
                var listed=candidates[i];
                if(opt.CardDefId==0 || rules!.Cards[opt.CardDefId].Entry!=listed.GetProperty("id").GetString()
                    || listed.GetProperty("upgrade").GetInt32()!=0 || listed.TryGetProperty("affliction",out _)
                    || listed.TryGetProperty("enchantment",out _))return "generated_option";
                options.Add(i+"/"+VisibleKey(listed),opt);continue;
            }
            int j=0;''')
    edit(path,"options.Add(i+\"/\"+VisibleKey(candidates[i]),opt);",'''var card=world.Cards[j];
            var listedCard=candidates[i];
            string? Name(string key)=>listedCard.TryGetProperty(key,out var v)?v.GetString():null;
            int Amount(string key)=>listedCard.TryGetProperty(key,out var v)?v.GetInt32():0;
            if(Name("enchantment")!=(card.EnchId==0?null:rules!.Enchantments[card.EnchId].Entry)
                || Amount("enchantment_amount")!=card.EnchAmt
                || Name("affliction")!=(card.AfflId==0?null:rules!.Afflictions[card.AfflId].Entry)
                || Amount("affliction_amount")!=card.AfflAmt)return "choice_modifier_value";
            options.Add(i+"/"+VisibleKey(listedCard),opt);''')
    edit(path,'if(!result.Executed)return "action_rejected";','''if(!result.Executed)return "action_rejected";
        if(play.Kind==HotActionKind.PlayCard && world.TerminalOutcome==HotCombatOutcome.Ongoing){
            var source=parent.Cards[play.SlotOrHandIdx];
            if(rules!.Cards[source.CardDefId].Entry=="OUTRAGE"){
                // Frozen Hot bytecode plays the original but omits the generated discard copy.
                if(source.AfflId!=0 || source.EnchId!=0 || source.CostModCount!=0)return "outrage_modified";
                var copy=HotCombatEngine.CreateFreshCard(ref world,rules.Cards[source.CardDefId],source.UpgradeLevel>0);
                HotCombatEngine.AddGeneratedCardInstance(ref world,ref cold,rules,scratch,in copy,HotPileKind.Discard,-1,true);
            }
        }''')
