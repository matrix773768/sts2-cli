"""Stage an opt-in public observation export on the SV1 graph host."""
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
    for file in ("SearchProbe.cs", "TurnGraph.cs"):
        shutil.copyfile(SV1 / file, staged / file)
    graph = staged / "TurnGraph.cs"
    edit = base["edit"]
    edit(graph, "        private readonly List<Vertex> _vertices = [];",
         """        private readonly List<Vertex> _vertices = [];
        private readonly bool _exportValue = Flag(request, "export_value");
        private readonly Dictionary<int, JsonElement> _publicDecisions = [];""")
    edit(graph, "            _maxMoves = Math.Max(_maxMoves, menu.Length);",
         """            if (_exportValue && !_oracle)
                _publicDecisions.Add(vertex.Id, JsonSerializer.SerializeToElement(
                    owner.ObserveNosl(owner._root, state), Wire));
            _maxMoves = Math.Max(_maxMoves, menu.Length);""")
    edit(graph, "                root = PublicState(seed), first_actions",
         """                public_decisions = _exportValue && !_oracle ? _publicDecisions : null,
                root = PublicState(seed), first_actions""")
    original = base["build"]
    compiler = FunctionType(original.__code__, original.__globals__ | {"HERE": staged})
    compiler(output, base["DATA"].resolve(), base["RITSU"].resolve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.output.resolve())
