"""Build the opt-in target and differential host against the pinned II-B Solver."""
from pathlib import Path
import runpy
import shutil

HERE = Path(__file__).resolve().parent
BASE = runpy.run_path(str(HERE.parent / "m1-nosl3c-iib/build_host.py"))
HOST = "m1-nosl3c-iid-build"


def stage(src):
    BASE["stage"](src)
    edit = BASE["BASE"]["BINDING"].edit
    shutil.copyfile(HERE / "TargetMenu.cs", src / "TargetMenu.cs")
    episode = src / "NoslPublicEpisode.cs"
    edit(episode, "bool StarX = false);", "bool StarX = false, string? TargetSide = null, string? TargetType = null);")
    edit(episode, '''        if (targets.Any(e => !sim.State.IsHittable(e)))
            throw new NotSupportedException("Alive enemy without qualified target mapping");''',
         '''        var allies = combat.Allies.Where(e => sim.State.GetCreature(e).IsAlive).ToArray();''')
    p = episode.read_text(encoding="utf-8")
    start = p.index("            if (type is not")
    end = p.index("            var id", start)
    p = p[:start] + '''            if (!TargetMenu.Supported(type))
                throw new NotSupportedException($"Unqualified target type: {type}");
''' + p[end:]
    start = p.index("            for (int slot")
    end = p.index("                var plan", start)
    p = p[:start] + '''            bool manual = TargetMenu.Manual(type);
            var roster = type == TargetType.AnyEnemy ? targets : allies;
            for (int slot = 0; slot < (manual ? roster.Length : 1); slot++)
            {
                int? target = manual ? slot : null;
                var entity = manual ? roster[slot] : null;
                if (entity != null && (!TargetMenu.Eligible(type, _player.Creature, entity)
                    || type == TargetType.AnyEnemy && !sim.State.IsHittable(entity)))
                    continue;
''' + p[end:]
    p = p.replace("enemy?.CombatId", "entity?.CombatId").replace("ImmediatePreview(sim, card, enemy)",
        "ImmediatePreview(sim, card, type == TargetType.AnyEnemy ? entity : null)")
    p = p.replace("StarX: card.Preview.HasStarCostX), plan);", '''StarX: card.Preview.HasStarCostX,
                    TargetSide: manual ? (type == TargetType.AnyEnemy ? "enemy" : "ally") : null,
                    TargetType: type.ToString()), plan);''')
    p = p.replace("            enemies = targets.Select", '''            allies = allies.Select((ally, i) => new
            {
                index = i, hp = sim.State.GetCreature(ally).CurrentHp,
                block = sim.State.GetCreature(ally).Block, attack_hits = Array.Empty<int>(),
                intents = Array.Empty<string>(), powers = PublicPowers(combat, ally),
            }).ToArray(),
            enemies = targets.Select''')
    episode.write_text(p, encoding="utf-8")

    sim = src / "RunSimulator.cs"
    p = sim.read_text(encoding="utf-8")
    start = p.index("        // Determine target based on card")
    end = p.index("        Log($\"Playing card", start)
    p = p[:start] + '''        var combat = CombatManager.Instance.DebugOnlyGetState()!;
        var type = card.TargetType;
        Creature? target = null;
        if (OfflineSearchHarness.TargetMenu.Manual(type))
        {
            bool enemy = type == TargetType.AnyEnemy;
            var roster = (enemy ? combat.Enemies : combat.Allies).Where(e => e.IsAlive).ToArray();
            string key = enemy ? "target_index" : "ally_index";
            if (!args.TryGetValue(key, out var raw) || raw == null)
                return Error($"Missing explicit {key}");
            int index = Convert.ToInt32(raw);
            if (index < 0 || index >= roster.Length || !card.CanPlayTargeting(roster[index]))
                return Error($"Invalid {key}");
            target = roster[index];
        }
        if (!card.CanPlayTargeting(target))
            return Error($"Cannot play {card.Id.Entry} with current target");

''' + p[end:]
    sim.write_text(p, encoding="utf-8")
    # Use native target predicates for the independent menu, even when no valid target exists.
    edit(sim, '                ["can_play"] = c.CanPlay(out _, out _),', '''                ["can_play"] = c.CanPlay(out _, out _),
                ["legal_target_indices"] = OfflineSearchHarness.TargetMenu.Manual(c.TargetType)
                    ? (c.TargetType == TargetType.AnyEnemy ? combatState!.Enemies : combatState!.Allies)
                        .Where(e => e.IsAlive).Select((entity, i) => (entity, i))
                        .Where(item => c.CanPlayTargeting(item.entity)).Select(item => item.i).ToArray()
                    : null,''')
    edit(src / "IntegrationProbe.cs", '        if (command == "i1_iib_native_stamp")', '''        if (command == "i1_iid_native_roster")
        {
            var rosterState = CombatManager.Instance.DebugOnlyGetState()!;
            return new() { ["type"] = "target_roster",
                ["enemy"] = rosterState.Enemies.Where(e => e.IsAlive).Select(e => e.CombatId).ToArray(),
                ["ally"] = rosterState.Allies.Where(e => e.IsAlive).Select(e => e.CombatId).ToArray() };
        }
        if (command == "i1_iid_prediction_roster")
            return (_episode ?? throw new InvalidOperationException("Reset first")).PredictionRoster();
        if (command == "i1_iid_prediction_text")
            return new() { ["type"] = "prediction_text", ["text"] = (_episode ?? throw new InvalidOperationException("Reset first")).PredictionText() };
        if (command == "i1_iib_native_stamp")''')
    edit(src / "InteractiveEpisode.cs", "    private void CloseInteractive()", '''    internal string PredictionText()
    {
        var snapshot = InteractiveProperty<SimulationSnapshot>("Current");
        return ContinuationStamp.CapturePredicted(_player, snapshot.Simulator,
            snapshot.Turn, EmptyForecast, snapshot.Turn).StateText;
    }

    internal Dictionary<string, object?> PredictionRoster()
    {
        var sim = InteractiveProperty<SimulationSnapshot>("Current").Simulator;
        var combat = (SimulatedCombatState)sim.State.CombatState;
        return new() { ["type"] = "target_roster",
            ["enemy"] = combat.KnownEnemies.Where(e => sim.State.GetCreature(e).IsAlive).Select(e => e.CombatId).ToArray(),
            ["ally"] = combat.Allies.Where(e => sim.State.GetCreature(e).IsAlive).Select(e => e.CombatId).ToArray() };
    }

    private void CloseInteractive()''')


if __name__ == "__main__":
    i1 = BASE["BASE"]["BINDING"].b1b.b1a.i1
    i1.build(i1.ROOT / "logs" / HOST, stage)
