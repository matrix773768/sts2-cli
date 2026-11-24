"""Read committed SV4A/DC2B ledger metadata without loading the training environment."""

from contextlib import closing, contextmanager
from hashlib import sha256
import json
import sqlite3


@contextmanager
def snapshot(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=4)) as db:
        db.execute("BEGIN")
        yield db


def identity(path):
    with snapshot(path) as db:
        contract, raw = db.execute("SELECT sha,json FROM contract").fetchone()
        rows = sha256()
        count = 0
        for ordinal, digest in db.execute("SELECT ordinal,sha FROM results ORDER BY ordinal"):
            rows.update(f"{ordinal}:{digest}\n".encode("ascii"))
            count += 1
    data = json.loads(raw)
    return dict(contract=contract, rows=rows.hexdigest(), count=count, model=data["definition"]["model"],
                manifest=data["manifest"], purpose=data["purpose"])
