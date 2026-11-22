"""Seed update 1 with this run's audited pair16 rows, leaving update 2 on-policy."""
from contextlib import closing
import gzip
import json
from pathlib import Path
from shutil import copyfile
import sqlite3
import sys


def seed(source, destination, *, solver_version="0.51.5-iii.8"):
    def roots(folder):
        return json.loads((folder / "course-roots.json").read_bytes())[0]

    assert roots(source) == roots(destination)
    src = (source / "training.sqlite").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(src, uri=True)) as old, closing(
            sqlite3.connect(destination / "training.sqlite")) as new:
        identity = "SELECT value FROM identity"
        a, b = (json.loads(db.execute(identity).fetchone()[0]) for db in (old, new))
        assert all(a[k] == b[k] for k in ("engine", "protocol", "source", "torch"))
        assert a["engine"]["solver"] == solver_version
        snapshot = "SELECT sha, payload FROM snapshots WHERE step = 0"
        assert old.execute(snapshot).fetchone() == new.execute(snapshot).fetchone()
        assert new.execute("SELECT count(*) FROM snapshots").fetchone() == (1,)
        assert new.execute("SELECT count(*) FROM roots").fetchone() == (0,)
        batches = old.execute("SELECT * FROM roots ORDER BY root").fetchall()
        hashes = old.execute("SELECT * FROM root_hashes ORDER BY root").fetchall()
        assert len(batches) == len(hashes) == 16
        for index, (phase, step, root, blob, _) in enumerate(batches):
            assert (phase, step, root) == ("train", 0, f"{index:06d}")
            item = json.loads(gzip.decompress(blob))
            assert item["spec"] == roots(source)[index]["spec"]
            assert all(row["qualification"]["certification"] == "exact_native_match"
                       for row in item["rows"] if row["feedback"]["eligible"])
            name = f"000000-{root}.json"
            target = destination / "audit" / name
            if target.exists():
                raise FileExistsError(target)
            copyfile(source / "audit" / name, target)
        with new:
            new.executemany("INSERT INTO roots VALUES (?, ?, ?, ?, ?)", batches)
            new.executemany("INSERT INTO root_hashes VALUES (?, ?, ?, ?)", hashes)


if __name__ == "__main__":
    seed(*(Path(arg) for arg in sys.argv[1:]))
