"""Compare deterministic v4 journal contents without printing stored trajectories."""
import argparse
from contextlib import closing
import gzip
import json
from pathlib import Path
import sqlite3


def read(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        identity, = db.execute("SELECT value FROM identity").fetchone()
        snapshots = db.execute("SELECT step,sha,payload,stats FROM snapshots ORDER BY step").fetchall()
        roots = []
        for phase, step, root, blob in db.execute(
                "SELECT phase,step,root,rows FROM roots ORDER BY phase,step,root"):
            batch = json.loads(gzip.decompress(blob))
            roots.append((phase, step, root, batch["status"], batch["spec"], batch["rows"]))
    return identity, snapshots, roots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cold", type=Path)
    parser.add_argument("resumed", type=Path)
    args = parser.parse_args()
    cold, resumed = read(args.cold), read(args.resumed)
    result = dict(identity_equal=cold[0] == resumed[0],
                  snapshots_equal=cold[1] == resumed[1], semantic_rows_equal=cold[2] == resumed[2])
    print(json.dumps(result | dict(snapshots=len(cold[1]), roots=len(cold[2]))))
    return 0 if all(result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
