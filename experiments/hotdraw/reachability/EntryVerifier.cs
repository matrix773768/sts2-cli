using System.Text.Json;
using System.Text.Json.Nodes;
using CombatSolver.HotDraw;
using CombatSolver.HotKernel;

namespace OfflineSearchHarness;

internal sealed record CycleRole(ushort Role, string Card, int Target, int Upgrade);
internal sealed record EntryTemplate(string Family, CycleRole[] Period, string? ReferencePublicState);
internal sealed record EntryProof(string Family, TraceStep[] Period, bool ReferenceMatch);
internal sealed record EntryResult(EntryProof? Witness, string? Unresolved)
{
    public static readonly EntryResult Absent = new(null, null);
}

internal sealed class EntryVerifier(Session session, StructureTrace trace, EntryTemplate[] templates, int limit)
{
    public int Attempts { get; private set; }
    private readonly Dictionary<(string Key, int Remaining), EntryResult> cache = [];

    public EntryResult Verify(Snapshot state, int remaining)
    {
        if (templates.Length == 0 || state.State.TerminalOutcome != HotCombatOutcome.Ongoing)
            return EntryResult.Absent;
        var key = (StructureTrace.ExactKey(state), remaining);
        if (cache.TryGetValue(key, out EntryResult? known))
            return known;
        string? unresolved = null;
        foreach (EntryTemplate template in templates)
        {
            if (template.Period.Length > remaining)
                continue;
            for (int rotation = 0; rotation < template.Period.Length; rotation++)
            {
                CycleRole[] pattern = [.. template.Period.Skip(rotation), .. template.Period.Take(rotation)];
                var bound = new Dictionary<ushort, ushort>();
                var moves = new List<(Snapshot Parent, HotAction Move, Transition Result)>();
                if (Walk(state, 0))
                {
                    TraceStep[] period = moves.Select(step => trace.Record(step.Parent, step.Move, step.Result)).ToArray();
                    bool exact = template.ReferencePublicState != null &&
                        NormalizePublic(session.PublicJson(state)) == template.ReferencePublicState;
                    var answer = new EntryResult(new EntryProof(template.Family, period, exact), null);
                    cache[key] = answer;
                    return answer;
                }

                bool Walk(Snapshot current, int depth)
                {
                    if (current.State.TerminalOutcome != HotCombatOutcome.Ongoing)
                        return false;
                    if (depth == pattern.Length)
                    {
                        var delta = trace.Delta(state, current);
                        return bound.Values.All(instance => Zone(state, instance) == Zone(current, instance)) &&
                            (delta.EnemyDurabilityRemoved > 0 || delta.PlayerPowerAmount > 0 || delta.Energy > 0);
                    }

                    CycleRole role = pattern[depth];
                    foreach (HotAction move in session.Actions(current, false))
                    {
                        BoundAction action = trace.Bind(current, move);
                        if (action.Kind != HotActionKind.PlayCard || action.Card != role.Card || action.Target != role.Target ||
                            current.State.Cards[move.SlotOrHandIdx].UpgradeLevel != role.Upgrade)
                            continue;
                        bool existing = bound.TryGetValue(role.Role, out ushort required);
                        if (existing ? required != action.Instance : bound.ContainsValue(action.Instance))
                            continue;
                        bound[role.Role] = action.Instance;
                        foreach (Transition result in Branches(current, move, Prefix.Empty))
                        {
                            moves.Add((current, move, result));
                            if (Walk(result.Child!, depth + 1))
                                return true;
                            moves.RemoveAt(moves.Count - 1);
                        }
                        if (!existing)
                            bound.Remove(role.Role);
                    }
                    return false;
                }
            }
        }
        var absent = new EntryResult(null, unresolved);
        cache[key] = absent;
        return absent;

        IEnumerable<Transition> Branches(Snapshot parent, HotAction action, Prefix prefix)
        {
            if (Attempts >= limit)
            {
                unresolved = "entry_budget";
                yield break;
            }
            Attempts++;
            Transition step = session.Advance(parent, action, prefix);
            if (step.Status == StepStatus.Completed)
            {
                yield return step;
                yield break;
            }
            if (step.Status == StepStatus.Unsupported)
            {
                unresolved ??= $"unsupported:{step.Point}:{step.Reason}";
                yield break;
            }
            if (step.Status == StepStatus.Error)
                throw new InvalidOperationException($"Entry probe: {step.Point}: {step.Reason}");
            var pending = step.Pending;
            IEnumerable<Prefix> branches = step.Status == StepStatus.NeedsChoice
                ? pending.Choices.Select(option => prefix.AddChoice(pending, option))
                : ReachPolicySearch.Support(pending).Select(option => prefix.AddDraw(pending, option.Id));
            foreach (Prefix next in branches)
                foreach (Transition outcome in Branches(parent, action, next))
                    yield return outcome;
        }
    }

    private static string Zone(Snapshot state, ushort instance)
    {
        for (int i = 0; i < state.State.TotalCardCount; i++)
        {
            if (state.State.Cards[i].CardUid != instance)
                continue;
            HotPileKind zone = HotPiles.PileOfIndex(in state.State, i);
            if (zone != HotPileKind.Draw)
                return zone.ToString();
            int top = Array.IndexOf(state.Belief.Top, instance);
            int bottom = Array.IndexOf(state.Belief.Bottom, instance);
            return top >= 0 ? $"top:{top}" : bottom >= 0 ? $"bottom:{bottom}" : "draw_unknown";
        }
        return "removed";
    }

    public static string NormalizePublic(string data)
    {
        var row = JsonNode.Parse(data)!.AsObject();
        row.Remove("Generation");
        foreach (string name in new[] { "hand", "play", "discard", "exhaust", "knownTop", "unknown", "knownBottom" })
        {
            if (row[name] is not JsonArray cards)
                continue;
            foreach (JsonNode? card in cards)
                card!.AsObject().Remove("instance");
            if (name == "unknown")
                row[name] = new JsonArray(cards.OrderBy(card => card!.ToJsonString(), StringComparer.Ordinal)
                    .Select(card => card!.DeepClone()).ToArray());
        }
        return row.ToJsonString();
    }

    public static EntryTemplate ReadTemplate(string family, JsonElement witness, TraceStep[] period)
    {
        JsonElement reference = witness.GetProperty("Start").GetProperty("state");
        var upgrades = new Dictionary<ushort, int>();
        foreach (string zone in new[] { "hand", "play", "discard", "exhaust", "knownTop", "unknown", "knownBottom" })
            foreach (JsonElement card in reference.GetProperty(zone).EnumerateArray())
                upgrades.Add(card.GetProperty("instance").GetUInt16(), card.GetProperty("upgrade").GetInt32());
        return new(family, period.Select(step =>
            new CycleRole(step.Move.Instance, step.Move.Card, step.Move.Target, upgrades[step.Move.Instance])).ToArray(),
            NormalizePublic(reference.GetRawText()));
    }
}
