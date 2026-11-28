import importlib.util
from pathlib import Path
path=Path(__file__).resolve().parents[1]/"m1-infra1h5/verify.py"
spec=importlib.util.spec_from_file_location("h5_verify",path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
check_segment=module.check_segment
