using System.Text.Json;

namespace Sts2Headless;

internal static partial class IntegrationProbe
{
    private static Dictionary<string, object?> ReferenceBatch(JsonElement cmd)
    {
        var episode = _episode ?? throw new InvalidOperationException("Reset first");
        var items = cmd.GetProperty("requests");
        if (items.GetArrayLength() > 32) throw new ArgumentOutOfRangeException("requests");
        foreach (var item in items.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object || !item.TryGetProperty("route", out var route) ||
                route.ValueKind != JsonValueKind.Array ||
                item.EnumerateObject().Any(p => p.Name != "route" && p.Name != "complete"))
                throw new ArgumentException("Expected a public reference route");
        }
        var results = new List<JsonElement>(items.GetArrayLength());
        foreach (var item in items.EnumerateArray())
        {
            // Materialize at the same boundary as a scalar reply, before the next
            // sibling can recycle a menu, a snapshot or a public observation.
            results.Add(JsonSerializer.SerializeToElement(episode.Reference(item), Program.JsonOpts));
        }
        return new() { ["type"]="infra1a.reference_batch.v1", ["results"]=results };
    }
}
