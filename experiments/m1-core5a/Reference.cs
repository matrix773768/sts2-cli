using System.Text.Json;
using CombatSolver;
using CombatSolver.Engine.InCombat.Simulation;

namespace OfflineSearchHarness;

internal sealed partial class FirstWin
{
    // Fork the live root. Only replay decisions of one public conditional policy.
    internal object Reference(JsonElement request)
    {
        var episode = (CombatBeamSolver.InteractiveCombat)_interactive!;
        var menu = _episodeMenu;
        var selector = _selectionMenu;
        var selected = _selection.ToArray();
        var stop = _interactiveStop;
        var detail = _interactiveDetail;
        var source = episode.Current;
        var root = _pre0bSolver!.TacticalFork(source);
        int calls = 0;
        try
        {
            using var session = _pre0bSolver.OpenInteractiveCombat(root);
            _interactive = session;
            var law = _law.Fork();
            bool replayedDraw=false;
            foreach (var edge in request.GetProperty("route").EnumerateArray())
            {
                var before = session.Current;
                var knowledge = KnowledgeChoice(before);
                bool choice = session.Waiting || knowledge != null;
                int index = edge.GetProperty("action").GetInt32();
                if (choice && replayedDraw) return new {kind="unresolved",reason="selector_draw_replay",calls};
                if (choice) InteractiveView();
                else ObserveNosl(_root, before);
                var draws = edge.GetProperty("draws").Deserialize<string[]>()!;
                using var tape = Observer(law, draws, true, false).Enter();
                using var probe = new SearchProbe(true){TurnDraw=tape}.Enter();
                calls++;
                try
                {
                    if (!choice) session.Play(_episodeMenu![index].Action);
                    else if (_selectionMenu![index].Choice is int card) _selection.Add(card);
                    else
                    {
                        if (knowledge != null) SubmitKnowledgeChoice(knowledge, _selection.Single(),session);
                        else session.Select(_selection.ToArray());
                        _selection.Clear();
                    }
                }
                catch (Exception) when (probe.Boundary != null) {}
                if (probe.Boundary == "strategic_c") return new {kind="C",state=tape.Strategic,calls};
                if (probe.Boundary == "public_draw" && tape.Used==draws.Length)
                    return new {kind="R",support=tape.Options,calls};
                if (probe.Boundary != null) return new {kind="unresolved",reason=probe.Boundary,calls};
                if (tape.Used!=draws.Length) throw new InvalidOperationException("Unused draw prefix");
                law=tape.Law;
                if (!choice) replayedDraw=tape.Used>0;
                var s=session.Current;
                if (!s.HasRisk && s.TerminalStamp!=null && (s.PlayerDead || s.AllEnemiesDead))
                    return new {kind=s.PlayerDead?"death":"victory",state=new {hp=s.PlayerHp,max_hp=s.PlayerMaxHp},calls};
                if (s.HasRisk || s.Turn!=source.Turn ||
                    (s.BoundaryReason!=SearchBoundaryReason.None && !session.Waiting && KnowledgeChoice(s)==null))
                    return new {kind="unresolved",reason="unsupported_boundary",calls};
            }
            var current=session.Current;
            if (!session.Waiting && KnowledgeChoice(current)==null)
                return new {kind="decision",state=ObserveNosl(_root,current),calls};
            var view=JsonSerializer.SerializeToElement(InteractiveView(),new JsonSerializerOptions{PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower});
            if(view.GetProperty("status").GetString()!="active")
                return new {kind="unresolved",reason="unsupported_selector",calls};
            return new {kind="decision",state=view.GetProperty("observation"),calls};
        }
        finally
        {
            _interactive=episode;
            _episodeMenu=menu;
            _selectionMenu=selector;
            _selection.Clear();
            _selection.AddRange(selected);
            _interactiveStop=stop;
            _interactiveDetail=detail;
            root.ReleaseSimulator();
        }
    }
}
