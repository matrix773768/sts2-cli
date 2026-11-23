"""Streaming, transactional reader for Ironclad prediction-only datasets."""
from contextlib import closing
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(encode(value)).hexdigest()


def batches(path, size=32, split=None, complete=True):
    """Yield verified batches of public records, excluding private root recipes."""
    if size < 1:
        raise ValueError("Expected positive batch size")
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        cursor = db.execute("""
            SELECT sha, payload FROM trajectories
            WHERE (? IS NULL OR split = ?) AND (? = 0 OR complete = 1)
            ORDER BY ordinal
        """, (split, split, int(complete)))
        while rows := cursor.fetchmany(size):
            batch = []
            for expected, payload in rows:
                data = gzip.decompress(payload)
                if sha256(data).hexdigest() != expected:
                    raise ValueError("Trajectory checksum mismatch")
                batch.append(json.loads(data))
            yield batch
