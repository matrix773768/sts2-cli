"""Execute the earlier native fixtures using the pinned integration host."""
from pathlib import Path
import runpy
import sys

integration = runpy.run_path(str(Path(__file__).with_name("run.py")))

fixture = Path(sys.argv.pop(1)).resolve()
integration["certification"].completion.bind = integration["bind"]
sys.path.insert(0, str(fixture.parent))
runpy.run_path(str(fixture), run_name="__main__")
