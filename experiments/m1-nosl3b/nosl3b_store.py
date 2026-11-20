"""Transactional per-root ledger and model/Adam checkpoints."""
from contextlib import closing
import gzip
from hashlib import sha256
import io
import json
import sqlite3

import torch

from nosl3b_protocol import digest
from nosl_experience import json_bytes
from nosl_model import Policy, checkpoint


def pack(value):
    return gzip.compress(json_bytes(value), compresslevel=3, mtime=0)


def unpack(payload):
    return json.loads(gzip.decompress(payload))


def tensor_bytes(value):
    stream = io.BytesIO()
    torch.save(value, stream)
    return stream.getvalue()


def tensors(payload):
    return torch.load(io.BytesIO(payload), weights_only=True, map_location="cpu")


class Store:
    def __init__(self, path, identity):
        self.db = sqlite3.connect(path)
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS identity (id INTEGER PRIMARY KEY CHECK (id = 1), value BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS roots (phase TEXT, step INTEGER, root TEXT, rows BLOB NOT NULL,
                    elapsed REAL NOT NULL, PRIMARY KEY (phase, step, root));
                CREATE TABLE IF NOT EXISTS snapshots (step INTEGER PRIMARY KEY, payload BLOB NOT NULL,
                    sha TEXT NOT NULL, stats BLOB NOT NULL);
                """)
            manifest = self.db.execute("SELECT value FROM identity WHERE id = 1").fetchone()
            if manifest is None:
                self.db.execute("INSERT INTO identity VALUES (1, ?)", (json_bytes(identity),))
        if manifest is not None and json.loads(manifest[0]) != identity:
            self.db.close()
            raise ValueError("Cannot resume with changed protocol, source or engine identity")

    def close(self):
        self.db.close()

    def done(self, phase, step):
        with closing(self.db.execute("SELECT root FROM roots WHERE phase=? AND step=?", (phase, step))) as cur:
            return {row[0] for row in cur}

    def append(self, phase, step, root, rows, elapsed):
        keys = {(r["arm"], r["initialization"], r["mode"], r["replicate"], r["iteration"]) for r in rows}
        if len(keys) != len(rows) or any(r["root"] != root for r in rows):
            raise ValueError("Conflicting or mismatched attempts in a root batch")
        with self.db:
            self.db.execute("INSERT INTO roots VALUES (?, ?, ?, ?, ?)", (phase, step, root, pack(rows), elapsed))

    def rows(self, phase, step=None):
        sql = "SELECT rows FROM roots WHERE phase=?"
        params = (phase,)
        if step is not None:
            sql += " AND step=?"
            params += (step,)
        with closing(self.db.execute(sql + " ORDER BY step, root", params)) as cur:
            for payload, in cur:
                yield from unpack(payload)

    def save(self, step, payload, stats):
        raw = tensor_bytes(payload)
        with self.db:
            self.db.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?)", (
                step, raw, sha256(raw).hexdigest(), pack(stats)))

    def latest(self):
        return self.db.execute("SELECT max(step) FROM snapshots").fetchone()[0]

    def load(self, step):
        payload, sha, stats = self.db.execute(
            "SELECT payload, sha, stats FROM snapshots WHERE step=?", (step,)).fetchone()
        if sha256(payload).hexdigest() != sha:
            raise ValueError("Damaged snapshot")
        return tensors(payload), unpack(stats)


def snapshot(arms, optimizers):
    return {key: dict(mechanics=p.mechanics, relations=p.relations, weights=p.state_dict(),
                      optimizer=optimizers[key].state_dict(), model_hash=digest(checkpoint(p)))
            for key, p in arms.items()}


def restore(snapshot_state, config, resume):
    arms, optimizers = {}, {}
    for key, state in snapshot_state.items():
        p = Policy(state["mechanics"], state["relations"]).eval()
        p.load_state_dict(state["weights"])
        if digest(checkpoint(p)) != state["model_hash"]:
            raise ValueError(f"Model digest mismatch in {key}")
        arms[key] = p
        if resume:
            optimizer = torch.optim.Adam(p.parameters(), lr=config["learning_rate"])
            optimizer.load_state_dict(state["optimizer"])
            optimizers[key] = optimizer
    return arms, optimizers
