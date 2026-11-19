"""Run frozen F3B/F4 on a cold native root and measure actual Replay work."""
from contextlib import contextmanager
from threading import Event
from time import monotonic, perf_counter
import runpy

from ls1_design import HERE, ROOT, PROTOCOL, STRATEGIES, read, file_hash, digest

s3a = runpy.run_path(str(HERE.parent / "m1-s3a/produce.py"))
bank, b1b, bind = (s3a[key] for key in ("bank", "b1b", "solver_binding"))
f3a, f3b = b1b.f5b.f3a, b1b.f5b.f3b
# runpy returns a copy of globals; bind reads the function's original globals.
PINNED = read(HERE.parent / "m1-f3a/manifest.json")["roots"]
F3A = ROOT / "logs/m1-f3a-formal"
RESOURCES = ("hp", "max_hp", "gold", "potions")


def setup(output, frozen=False):
    host = "m1-s3a-build" if frozen else "m1-ls1-build"
    bind.__globals__["HOST"] = host
    adapter = file_hash(HERE / "build.py", True)
    # Formatting-only change with identical staged C# preserves the frozen adapter identity.
    if adapter == "54fba124006d7cb6c56ce50c551bd234d298f501b90983e46f96e9a9116806c4":
        adapter = "4f988fc822bce55f8234a1ca1ee86971c44941d8a947b9ef528b56a560339fd1"
    return bind(output, PROTOCOL["solver"], ROOT / "logs/m1-e3f/release") | {"adapter": adapter} | {
        name: file_hash(path, True) for name, path in {
            "f3b_first_win": HERE.parent / "m1-f3b/FirstWin.cs",
            "f3b_route_search": HERE.parent / "m1-f3b/RouteSearch.cs",
            "f4_quality": HERE.parent / "m1-f4/QualitySearch.cs",
            "preprocess": HERE.parent / "m1-n2e/semantics.py",
            "catalog": HERE.parent / "m1-n2e/cards.json",
        }.items()
    }


@contextmanager
def restore(output, case, versions, deadline):
    with b1b.Session(output, deadline, Event()) as game:
        checkpoint = None
        if case["source"] == "F3A":
            root = next(r for r in PINNED if r["id"] == case["id"])
            checkpoint = F3A / root["checkpoint"]
            if file_hash(checkpoint) != case["checkpoint_sha256"]:
                raise ValueError("Checkpoint differs from experiment manifest")
            before = game.request("load_save", path=str(checkpoint), lang="en")
            if before["decision"] != "map_select":
                raise ValueError("F3A checkpoint does not start at map selection")
            public = game.execute_action(root["entry"])
            identity = game.request("f1_begin")
            f3a.equal("F3A public root", root["public_root"], public)
            f3a.equal("F3A native root", root["identity"], identity)
        actual = game.request("i1_s3a_identity")
        if (actual["sha256"], actual["version"].split("+", 1)[0]) != (versions["solver_sha256"], versions["solver"]):
            raise ValueError("Runtime Solver differs from experiment binding")
        if case["source"] == "synthetic":
            b1b.validate(case["spec"])
            surfaces, _ = b1b.synth.capture(game, case["spec"])
            identity, public = surfaces["identity"], surfaces["public_root"]
        try:
            yield game, public, identity
        finally:
            if checkpoint is not None and file_hash(checkpoint) != case["checkpoint_sha256"]:
                raise ValueError("F3A checkpoint changed")


def ms(start):
    return (perf_counter() - start) * 1000


def request(game, cmd, cap, **extra):
    response = game.request(cmd, cap=cap, arm="C", potions=False, rejected=[], **extra)
    result = response.get("search")
    if result is None:
        return dict(status=response["status"], transitions=0)
    if result["cap"] != cap or not 0 <= result["transitions"] <= cap or not result["root_unchanged"]:
        raise ValueError("Native search accounting invariant violated")
    return result


def terminal(route):
    return {k: route[k] for k in RESOURCES} | {"hp_lost": route["hp_lost"]}


def search(game, first_cap, total_cap, *, order=None, teacher=None, ordering_ms=0, model_ms=0):
    before = game.request("f1_audit")
    start = perf_counter()
    extra = {}
    if order is not None:
        extra["ls1_order"] = list(order)
    if teacher is not None:
        extra["ls1_probe"] = teacher
    first = request(game, "i1_f3b", first_cap, **extra)
    first_ms = ms(start) + ordering_ms
    search_paths = first.get("routes", [])
    attempted = [r["plan"]["strategy"] for r in search_paths if r["plan"].get("parent_route_id") is None]
    expected = (teacher,) if teacher else (order or STRATEGIES)
    if attempted != list(expected[:len(attempted)]):
        raise ValueError("Actual initial route order differs from scheduled order")
    attempts = [
        dict(strategy=r["plan"]["strategy"], kind=r["plan"]["repair_reason"], status=r["stop"],
             detail=r.get("detail"), transitions=r["transitions"], at=r["last_transition"],
             rollout_ms=r["rollout_ms"])
        for r in search_paths
    ]
    row = dict(first_cap=first_cap, cap=total_cap, search_status=first["status"], status=first["status"],
               detail=first.get("detail"), transitions=first["transitions"], first_ms=None,
               ordering_ms=ordering_ms, model_ms=model_ms, first_transitions=None, attempts=attempts,
               planned=list(expected), executed_initial=attempted, first_locked=None, locked=None, qualified_first_ms=None,
               verification_transitions=0, quality_transitions=0, first_key=first.get("winner_key"),
               locked_key=None, first_path_size=None, route_risks=[], quality_status=None, lock_at=None)
    if first["status"] == "predicted_win":
        frame = first["history"][first["winner_node"]]["frame"]
        seed = dict(frame, hp_lost=frame["cumulative_loss"], key=first["winner_key"], at=0)
        actions = [f3b.action_for_wire(a) for a in first["actions"]]
        length = len(actions)
        row.update(first_ms=first_ms, first_transitions=first["transitions"], first_path_size=length)
        remaining = total_cap - first["transitions"]
        if length > remaining:
            raise ValueError("Insufficient reserved budget for incumbent verification")
        # The frozen F4 rebuild checks every legal action and continuation stamp.
        # Exactly length transitions locks the candidate without a refinement rollout.
        verify_started = perf_counter()
        quality = request(game, "i1_f4", length if teacher else remaining,
                          seed_actions=actions, seed_stamps=first["stamps"], include_history=False)
        if "root_stamp" in quality and quality["root_stamp"] != first["root_stamp"]:
            raise ValueError("F4 reconstructed a different prediction root")
        row.update(status="verification_failed", transitions=row["transitions"] + quality["transitions"],
                   verification_transitions=quality.get("seed_transitions", 0),
                   quality_transitions=quality["transitions"] - quality.get("seed_transitions", 0),
                   quality_status=quality["status"])
        if quality.get("seed_verified", quality.get("seed_transitions") == length
                       and quality.get("detail") is None):
            eligible = [c for c in quality["candidates"] if c["potions"] == seed["potions"]]
            winner = max([seed, *eligible], key=lambda c: (c["hp"], -c["at"]))
            locked_actions = actions if not winner["at"] else winner["actions"]
            if f3b.action_for_wire(locked_actions[-1])["kind"] == "EndTurn":
                row["route_risks"].append("E3_ENEMY_SIDE_TERMINAL")
            row.update(status="qualified_win" if winner["hp"] >= PROTOCOL["min_locked_hp"] else "below_hp_floor",
                       first_locked=terminal(seed), locked=terminal(winner), locked_key=winner["key"],
                       qualified_first_ms=(first_ms + quality["seed_lock_ms"] if "seed_lock_ms" in quality
                                           else first_ms + ms(verify_started)),
                       lock_at=first["transitions"] + (winner["at"] or length))
    row["search_ms"] = ms(start) + ordering_ms
    if row["transitions"] > total_cap or game.request("f1_audit") != before:
        raise ValueError("Experiment budget exceeded or live source mutated")
    row["root_stamp"] = first.get("root_stamp")
    return row


def semantic(row):
    fields = ("first_cap", "cap", "status", "search_status", "transitions", "first_transitions", "first_key",
              "locked_key", "first_path_size", "first_locked", "locked", "verification_transitions",
              "quality_transitions", "quality_status", "lock_at", "route_risks", "planned", "executed_initial", "root_stamp")
    return {k: row[k] for k in fields} | {"attempts": [
        {k: r[k] for k in ("strategy", "kind", "status", "detail", "transitions", "at")} for r in row["attempts"]
    ]}
