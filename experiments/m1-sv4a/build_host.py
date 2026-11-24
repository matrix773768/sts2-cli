"""Add a lightweight, public-only wire mode to the SV1 turn graph."""
import argparse
from pathlib import Path
import runpy
import shutil
from types import FunctionType

HERE = Path(__file__).resolve().parent
SV1 = HERE.parent / "m1-sv1"


def build(output):
    base = runpy.run_path(str(SV1 / "build.py"))
    staged = output.with_name(output.name + "-overlay")
    staged.mkdir(parents=True, exist_ok=False)
    for name in ("TurnGraph.cs", "SearchProbe.cs"):
        shutil.copyfile(SV1 / name, staged / name)
    graph = staged / "TurnGraph.cs"
    edit = base["edit"]
    edit(graph, "        private readonly List<Vertex> _vertices = [];",
         """        private readonly List<Vertex> _vertices = [];
        private readonly bool _publicRun = Flag(request, "public_run");
        private readonly Dictionary<int, object> _publicDecisions = [];""")
    edit(graph, "            var stamp = MeasureState(state);",
         """            if (_publicRun)
            {
                Add(parent, move, new Outcome(kind, reason, "", kind is "victory" or "death"
                    ? new { hp = state.PlayerHp, max_hp = state.PlayerMaxHp }
                    : new { }), null);
                return;
            }
            var stamp = MeasureState(state);""")
    edit(graph, "            _maxMoves = Math.Max(_maxMoves, menu.Length);",
         """            if (_publicRun)
                _publicDecisions.Add(vertex.Id, owner.ObserveNosl(owner._root, state));
            _maxMoves = Math.Max(_maxMoves, menu.Length);""")
    edit(graph, "                    var nextLineage = Append(lineage, move, _identityRule) +",
         '                    var nextLineage = (_publicRun ? "" : Append(lineage, move, _identityRule)) +')
    edit(graph, "                        var endStamp = MeasureState(state);",
         '                        var endStamp = _publicRun ? "" : MeasureState(state);')
    edit(graph, """new Outcome("end_play_a", null, HashText(endStamp),
                            new { state = PublicState(state) })""",
         """new Outcome("end_play_a", null, _publicRun ? "" : HashText(endStamp),
                            _publicRun ? new { } : new { state = PublicState(state) })""")
    edit(graph, "                    string key = MeasureState(next) + lineage;",
         "                    string? key = _publicRun ? null : MeasureState(next) + lineage;")
    edit(graph, """            var root = Add(null, null, null, waiting ? null : MeasureState(seed));""",
         """            if (_publicRun && (_mode != "tree" || _oracle || _potionsEnabled))
                throw new ArgumentException("The public wire requires the unmerged NOSL play menu");
            var root = Add(null, null, null, waiting || _publicRun ? null : MeasureState(seed));""")
    edit(graph, "            Propagate();",
         """            if (_publicRun)
            {
                var clock = _clock.Elapsed.TotalMilliseconds;
                return new()
                {
                    ["type"] = "sv4a_public_graph", ["stop"] = _stop, ["transitions"] = _transitions,
                    ["states"] = _publicDecisions.Count, ["nodes"] = _vertices.Count, ["graph_ms"] = clock,
                    ["solver_ms"] = Ms(_transferTicks), ["menu_ms"] = Ms(_menuTicks),
                    ["observations"] = JsonSerializer.SerializeToElement(_publicDecisions, Wire),
                    ["edges"] = JsonSerializer.SerializeToElement(_edges, Wire),
                    ["boundaries"] = JsonSerializer.SerializeToElement(_vertices.Where(v => v.Outcome != null)
                        .Select(v => new { v.Id, v.Outcome!.Kind, v.Outcome.Reason, v.Outcome.Public }), Wire),
                };
            }
            Propagate();""")
    original = base["build"]
    compiler = FunctionType(original.__code__, original.__globals__ | {"HERE": staged})
    compiler(output, base["DATA"].resolve(), base["RITSU"].resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    build(parser.parse_args().output.resolve())
