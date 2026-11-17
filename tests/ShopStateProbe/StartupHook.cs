using System;
using System.Collections;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;

public static class StartupHook
{
    public static void Initialize() => Console.SetOut(new Observe(Console.Out));

    private sealed class Observe : TextWriter
    {
        private readonly TextWriter output;
        private readonly ConditionalWeakTable<object, Tag> tags = new();
        private int nextTag, line;
        public Observe(TextWriter output) => this.output = output;
        public override Encoding Encoding => output.Encoding;
        public override void WriteLine(string text)
        {
            if (text != null && text.StartsWith("{"))
            {
                line++;
                try { Capture(text); }
                catch (Exception error) { Console.Error.WriteLine("[SHOPPROBE-ERROR] " + error); }
            }
            output.WriteLine(text);
        }
        public override void Flush() => output.Flush();

        private static object Property(object obj, string key) =>
            obj?.GetType().GetProperty(key, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(obj);

        private void Capture(string text)
        {
            using var json = JsonDocument.Parse(text);
            var root = json.RootElement;
            if (root.GetProperty("type").GetString() is "ready" or "quit_result") return;
            var assembly = AppDomain.CurrentDomain.GetAssemblies().First(a => a.GetName().Name == "sts2");
            var type = assembly.GetType("MegaCrit.Sts2.Core.Runs.RunManager", true);
            var manager = type.GetProperty("Instance").GetValue(null);
            var sync = Property(manager, "MerchantSynchronizer");
            var state = Property(manager, "State");
            var players = Property(state, "Players") as IList;
            var player = players == null || players.Count == 0 ? null : players[0];
            var inventoryField = sync?.GetType().GetField("_inventories", BindingFlags.Instance | BindingFlags.NonPublic);
            var inventories = inventoryField?.GetValue(sync) as IList;
            object inventory = inventories != null && inventories.Count > 0 ? inventories[0] : null;
            int? inventoryTag = inventory == null ? null : tags.GetValue(inventory, _ => new Tag(++nextTag)).Id;
            var removal = Property(inventory, "CardRemovalEntry");
            var odds = Property(Property(state, "Odds"), "UnknownMapPoint");

            Console.Error.WriteLine("[SHOPPROBE] " + JsonSerializer.Serialize(new {
                line, inventoryTag, count = inventories?.Count,
                matchingPlayer = inventory == null ? (bool?)null : ReferenceEquals(player, Property(inventory, "Player")),
                inFlight = inventory?.GetType().GetField("_purchaseInFlight", BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(inventory),
                removalStocked = Property(removal, "IsStocked"),
                stock = (Property(inventory, "AllEntries") as IEnumerable)?.Cast<object>().Select(entry => new {
                    id = Property(entry, "Id"), cost = Property(entry, "Cost"),
                    stocked = Property(entry, "IsStocked")
                }).ToArray(),
                gold = Property(player, "Gold"),
                deck = CountOf(Property(Property(player, "Deck"), "Cards")),
                potions = (Property(player, "Potions") as IEnumerable)?.Cast<object>().Count(x => x != null),
                relics = CountOf(Property(player, "Relics")),
                room = Property(state, "CurrentRoom")?.GetType().Name,

                unknownOdds = new { monster=Property(odds,"MonsterOdds"), elite=Property(odds,"EliteOdds"), shop=Property(odds,"ShopOdds"), treasure=Property(odds,"TreasureOdds") }
            }));
        }

        private static int? CountOf(object value) =>
            (value as IEnumerable)?.Cast<object>().Count();

        private sealed class Tag
        {
            public Tag(int id) => Id = id;
            public int Id { get; }
        }
    }
}
