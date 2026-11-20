"""Checksummed durable roots and immutable model/optimizer journals."""
from contextlib import closing
from hashlib import sha256
import os
from pathlib import Path

import torch

from protocol import MODEL_VERSION, digest
from nosl3b_store import Store, pack, unpack, restore, snapshot
from nosl_model import Policy, checkpoint


class Journal(Store):
    def __init__(self, path, identity):
        super().__init__(path, identity)
        with self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS root_hashes
               (phase TEXT, step INTEGER, root TEXT, sha TEXT NOT NULL, PRIMARY KEY(phase,step,root))""")
        try:
            self.verify()
        except BaseException:
            self.close()
            raise

    def verify(self):
        if self.db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        query = """SELECT roots.rows, root_hashes.sha FROM roots
                   LEFT JOIN root_hashes USING (phase,step,root)"""
        with closing(self.db.execute(query)) as rows:
            for raw, sha in rows:
                if sha256(raw).hexdigest() != sha:
                    raise ValueError("Root ledger checksum mismatch")
        with closing(self.db.execute("SELECT payload, sha FROM snapshots")) as models:
            for raw, sha in models:
                if sha256(raw).hexdigest() != sha:
                    raise ValueError("Checkpoint checksum mismatch")

    def commit_root(self, phase, step, batch):
        key = (phase, step, batch["root"])
        raw = pack(batch)
        with self.db:
            self.db.execute("INSERT INTO roots VALUES (?, ?, ?, ?, ?)", (*key, raw, batch["timing"]["total_ms"] / 1000))
            self.db.execute("INSERT INTO root_hashes VALUES (?, ?, ?, ?)", (*key, sha256(raw).hexdigest()))

    def batches(self, phase, step=None):
        sql = """SELECT rows, sha FROM roots JOIN root_hashes USING (phase,step,root) WHERE phase=?"""
        args = (phase,)
        if step is not None:
            sql += " AND step=?"
            args += (step,)
        with closing(self.db.execute(sql + " ORDER BY step, root", args)) as rows:
            for raw, sha in rows:
                if sha256(raw).hexdigest() != sha:
                    raise ValueError("Root ledger checksum mismatch")
                yield unpack(raw)

    def rows(self, phase, step=None):
        for batch in self.batches(phase, step):
            yield from batch["rows"]


def fresh(config):
    torch.manual_seed(config["initialization_seed"])
    policy = Policy(True, True).eval()
    return policy, torch.optim.Adam(policy.parameters(), lr=config["learning_rate"])


def state(policy, optimizer, config, step):
    return dict(model_version=MODEL_VERSION, weights=snapshot({"mechanism": policy}, {"mechanism": optimizer}),
                torch_rng=torch.get_rng_state(), policy_seed=config["policy_seed"],
                next_root=step * config["roots_per_update"], update=step,
                model_sha256=digest(checkpoint(policy)))


def load(saved, config, step):
    if (saved["model_version"] != MODEL_VERSION or saved["policy_seed"] != config["policy_seed"] or
            saved["next_root"] != step * config["roots_per_update"] or saved["update"] != step):
        raise ValueError("Checkpoint does not match sampling position")
    models, optimizers = restore(saved["weights"], config, True)
    torch.set_rng_state(saved["torch_rng"])
    model = models["mechanism"]
    if saved["model_sha256"] != digest(checkpoint(model)):
        raise ValueError("Checkpoint model hash mismatch")
    return model, optimizers["mechanism"]


def atomic_bytes(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)