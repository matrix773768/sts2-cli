"""Charge each host build and experiment against the independent H2 worker budget."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-infra1h"))
import campaign

campaign.LOG = campaign.ROOT / "logs/infra1h2"
campaign.BOOK = campaign.LOG / "ledger.jsonl"
if __name__ == "__main__":
    campaign.charge(sys.argv[1], [sys.executable, "-B", HERE / sys.argv[2], *sys.argv[3:]])
