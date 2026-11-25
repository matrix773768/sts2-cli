using CombatSolver.HotKernel;

namespace CombatSolver.HotDraw;

// Arrays belong to a snapshot. Updates return a new belief and share only unchanged arrays.
internal sealed record DrawBelief(ushort[] Top, ushort[] Unknown, ushort[] Bottom, int Generation)
{
    public static DrawBelief Create(IEnumerable<ushort> top, IEnumerable<ushort> exchangeable,
        IEnumerable<ushort> bottom)
    {
        var belief = new DrawBelief(top.ToArray(), exchangeable.Order().ToArray(), bottom.ToArray(), 0);
        ushort[] ids = belief.OrderedIds().ToArray();
        if (ids.Contains((ushort)0) || ids.Distinct().Count() != ids.Length)
            throw new ArgumentException("The public pile must bind distinct, nonzero instance identities.");
        return belief;
    }

    public IEnumerable<ushort> OrderedIds() => Top.Concat(Unknown).Concat(Bottom);

    public OutcomeOption[] Options()
    {
        if (Top.Length > 0)
            return [new(Top[0], 1)];
        if (Unknown.Length > 0)
            return Unknown.Select(uid => new OutcomeOption(uid, Unknown.Length)).ToArray();
        if (Bottom.Length > 0)
            return [new(Bottom[0], 1)];
        throw new InvalidOperationException("Draw requested from an empty belief.");
    }

    public DrawBelief Draw(ushort uid)
    {
        if (Top.Length > 0 && Top[0] == uid)
            return this with { Top = Top[1..] };
        if (Top.Length == 0 && Unknown.Contains(uid))
            return this with { Unknown = Unknown.Where(id => id != uid).ToArray() };
        if (Top.Length == 0 && Unknown.Length == 0 && Bottom.Length > 0 && Bottom[0] == uid)
            return this with { Bottom = Bottom[1..] };
        throw new InvalidOperationException("Draw instance is outside the current public support.");
    }

    public DrawBelief Insert(ushort uid, bool top)
    {
        if (OrderedIds().Contains(uid))
            throw new InvalidOperationException("Duplicate instance in the public pile.");
        return top ? this with { Top = [uid, .. Top] } : this with { Bottom = [.. Bottom, uid] };
    }

    public DrawBelief Shuffle(IEnumerable<ushort> ids) => Create([], ids, []) with { Generation = Generation + 1 };

    public void Validate(in CombatHotState state, bool keepWorldOrder)
    {
        int count = Top.Length + Unknown.Length + Bottom.Length;
        if (state.DrawCount != count)
            throw new InvalidOperationException("Draw pile size disagrees with the public belief.");
        var seen = new HashSet<ushort>();
        for (int i = 0; i < state.TotalCardCount; i++)
        {
            ushort uid = state.Cards[i].CardUid;
            if (uid == 0 || !seen.Add(uid))
                throw new InvalidOperationException("Card instance identity was lost or duplicated.");
        }
        for (int i = 0; i < Top.Length; i++)
            Check(in state, i, Top[i]);
        for (int i = 0; i < Bottom.Length; i++)
            Check(in state, count - Bottom.Length + i, Bottom[i]);
        if (keepWorldOrder)
        {
            for (int i = 0; i < Unknown.Length; i++)
            {
                if (Array.BinarySearch(Unknown, state.Cards[state.DrawStart + Top.Length + i].CardUid) < 0)
                    throw new InvalidOperationException("World pile has an instance outside the public belief.");
            }
        }
        else
        {
            for (int i = 0; i < Unknown.Length; i++)
                Check(in state, Top.Length + i, Unknown[i]);
        }

        static void Check(in CombatHotState state, int offset, ushort expected)
        {
            if (state.Cards[state.DrawStart + offset].CardUid != expected)
                throw new InvalidOperationException("Known draw order or canonical unknown layout was violated.");
        }
    }
}
