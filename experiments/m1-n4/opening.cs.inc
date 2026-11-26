        if (fixture && fixtureOptions.TryGetProperty("n4_order", out var ordered))
        {
            var pc = player.PlayerCombatState!;
            int handCount = pc.Hand.Cards.Count;
            var remaining = pc.Hand.Cards.Concat(pc.DrawPile.Cards).ToList();
            if (handCount != 5 || remaining.Count != spec.Deck.Length ||
                pc.DiscardPile.Cards.Count != 0 || pc.ExhaustPile.Cards.Count != 0)
                return Error("n4_ineligible_opening_zones");
            var assigned = new List<CardModel>();
            foreach (var card in spec.Deck)
            {
                int i = remaining.FindIndex(c => c.Id.Entry == card.Id && c.CurrentUpgradeLevel == card.Upgrade);
                if (i < 0) return Error("n4_opening_instance_mismatch");
                assigned.Add(remaining[i]);
                remaining.RemoveAt(i);
            }
            var slots = ordered.EnumerateArray().Select(s => s.GetInt32()).ToArray();
            if (remaining.Count != 0 || slots.Length != assigned.Count ||
                slots.Any(i => i < 0 || i >= assigned.Count) || slots.Distinct().Count() != slots.Length)
                return Error("n4_incomplete_permutation");
            pc.Hand.Clear(silent: true);
            pc.DrawPile.Clear(silent: true);
            for (int i = 0; i < assigned.Count; i++)
                (i < handCount ? pc.Hand : pc.DrawPile).AddInternal(assigned[slots[i]], silent: true);
        }
