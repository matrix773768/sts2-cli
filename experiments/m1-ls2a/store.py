"""Transactional, versioned journals and compressed content-addressed results."""
from contextlib import contextmanager
import gzip
import json
import sqlite3
from time import time

from space import digest


SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
  plan TEXT PRIMARY KEY, manifest BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS payloads (
  cache TEXT PRIMARY KEY, exact TEXT, data BLOB NOT NULL, sha TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  plan TEXT NOT NULL, id TEXT NOT NULL, ordinal INTEGER NOT NULL, cache TEXT NOT NULL,
  cap INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','active','done','failed')),
  PRIMARY KEY (plan,id)
);
CREATE TABLE IF NOT EXISTS attempts (
  plan TEXT NOT NULL, id TEXT NOT NULL, attempt INTEGER NOT NULL,
  reserved INTEGER NOT NULL, charged INTEGER, state TEXT NOT NULL,
  data BLOB, started REAL NOT NULL, finished REAL, PRIMARY KEY(plan,id,attempt)
);
CREATE TABLE IF NOT EXISTS batches (
  plan TEXT NOT NULL, number INTEGER NOT NULL, data BLOB NOT NULL, PRIMARY KEY(plan,number)
);
"""


def pack(data):
    return gzip.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                         .encode("utf-8"), compresslevel=3, mtime=0)


def unpack(data):
    return json.loads(gzip.decompress(data))


def open_store(path):
    connection = sqlite3.connect(path, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(SCHEMA)
    return connection


@contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    with db:
        yield


def register(db, manifest, jobs):
    plan = manifest["name"]
    frozen = db.execute("SELECT manifest FROM plans WHERE plan=?", (plan,)).fetchone()
    if frozen:
        if unpack(frozen[0]) != manifest:
            raise ValueError("Immutable dataset name already points to a different manifest")
        return
    with transaction(db):
        db.execute("INSERT INTO plans VALUES (?,?)", (plan, pack(manifest)))
        db.executemany("INSERT INTO tasks VALUES (?,?,?,?,?,'pending')",
                       [(plan, job["id"], i, job["cache"], job["reserved"]) for i, job in enumerate(jobs)])


def recover(db, plan, attempts_max):
    with transaction(db):
        rows = db.execute("SELECT id,attempt FROM attempts WHERE plan=? AND state='active'", (plan,)).fetchall()
        for id_, attempt in rows:
            db.execute("""UPDATE attempts SET state='interrupted',charged=reserved,finished=?
                          WHERE plan=? AND id=? AND attempt=?""", (time(), plan, id_, attempt))
            db.execute("UPDATE tasks SET state=? WHERE plan=? AND id=?",
                       ("pending" if attempt < attempts_max else "failed", plan, id_))
    return len(rows)


def payload(db, cache):
    row = db.execute("SELECT data,sha FROM payloads WHERE cache=?", (cache,)).fetchone()
    if row is None:
        return None
    result = unpack(row[0])
    if digest(result) != row[1]:
        raise ValueError("Stored payload checksum differs")
    return result


def pending(db, plan):
    return db.execute("""SELECT id,cache,cap FROM tasks WHERE plan=? AND state='pending'
                         ORDER BY ordinal""", (plan,)).fetchall()


def charged(db, plan):
    return db.execute("SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM attempts WHERE plan=?",
                      (plan,)).fetchone()[0]


def reserve(db, plan, id_, cap, *, hit=False):
    with transaction(db):
        db.execute("UPDATE tasks SET state=? WHERE plan=? AND id=? AND state='pending'",
                   ("done" if hit else "active", plan, id_))
        number = db.execute("SELECT COUNT(*) FROM attempts WHERE plan=? AND id=?", (plan, id_)).fetchone()[0] + 1
        db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,NULL,?,?)",
                   (plan, id_, number, cap, 0 if hit else None, "cached" if hit else "active",
                    time(), time() if hit else None))
    return number


def finish(db, plan, job, number, item, attempts_max):
    cache = job["cache"]
    cap = job["reserved"]
    temporary = item["outcome"] == "transient"
    value = sum(c["outcome"].get("transitions") or 0 for c in item["cells"])
    if value > cap:
        raise ValueError("Execution exceeded its reserved transition budget")
    if temporary or any(c["outcome"].get("transitions") is None for c in item["cells"]):
        value = cap
    state = "pending" if temporary and number < attempts_max else ("failed" if temporary else "done")
    with transaction(db):
        if state == "done":
            db.execute("INSERT INTO payloads VALUES (?,?,?,?)",
                       (cache, item.get("exact"), pack(item), digest(item)))
        db.execute("UPDATE attempts SET state=?,charged=?,data=?,finished=? WHERE plan=? AND id=? AND attempt=?",
                   ("retryable" if temporary else "complete", value,
                    pack(item) if temporary else None, time(), plan, job["id"], number))
        db.execute("UPDATE tasks SET state=? WHERE plan=? AND id=?", (state, plan, job["id"]))
    return state


def results(db, plan):
    for id_, cache, state in db.execute("SELECT id,cache,state FROM tasks WHERE plan=? ORDER BY ordinal", (plan,)):
        if state == "done":
            yield id_, payload(db, cache)
        elif state == "failed":
            row = db.execute("""SELECT data,state FROM attempts WHERE plan=? AND id=? ORDER BY attempt DESC LIMIT 1""",
                             (plan, id_)).fetchone()
            yield id_, unpack(row[0]) if row[0] else {"outcome": row[1], "cells": []}


def batch(db, plan, row):
    n = db.execute("SELECT COUNT(*) FROM batches WHERE plan=?", (plan,)).fetchone()[0] + 1
    with db:
        db.execute("INSERT INTO batches VALUES (?,?,?)", (plan, n, pack(row)))
