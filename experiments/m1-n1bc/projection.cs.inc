            mechanism = new
            {
                played = combat.GetCardsPlayedThisTurn(_player.Creature),
                attacks = combat.GetAttacksPlayedThisTurn(_player.Creature),
                skills = combat.GetSkillCardsPlayedThisTurn(_player.Creature),
                // Restrict amounts to named visible combat buffs and debuffs.
                stacks = combat.EffectivePowers().Where(p => p.Id.Entry is
                    "RITUAL_POWER" or "ARTIFACT_POWER" or "PLATING_POWER" or "INTANGIBLE_POWER" or
                    "THORNS_POWER" or "METALLICIZE_POWER" or "BARRICADE_POWER" or "DARK_EMBRACE_POWER" or
                    "FEEL_NO_PAIN_POWER" or "CORRUPTION_POWER" or "DEMON_FORM_POWER" or "RAGE_POWER" or
                    "FLAME_BARRIER_POWER" or "NO_DRAW_POWER" or "CURL_UP_POWER" or "ENRAGE_POWER")
                    .Where(p => ReferenceEquals(p.Owner, _player.Creature) || targets.Contains(p.Owner))
                    .Select(p => new { owner = Array.IndexOf(targets, p.Owner), id = p.Id.Entry, amount = p.Amount })
                    .OrderBy(p => p.owner).ThenBy(p => p.id, StringComparer.Ordinal).ThenBy(p => p.amount).ToArray(),
                species = targets.Select(e => e.Monster?.Id.Entry).ToArray(),
            },
