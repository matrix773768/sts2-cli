"""Versioned public experience and eligibility for terminal Monte Carlo returns."""
import gzip
import hashlib
import json

OBSERVATION = "sts2.nosl_observation.v1"
TRANSITION = "sts2.nosl_transition.v1"
EPISODE = "sts2.nosl_episode.v1"
OBS_FIELDS = ("turn", "hp", "max_hp", "block", "energy", "draw_count", "hand",
              "discard", "exhaust", "deck", "powers", "potions", "relics", "enemies", "actions")
CARD_FIELDS = ("index", "id", "upgrade", "cost", "enchantment", "enchantment_amount",
               "affliction", "affliction_amount")
ACTION_FIELDS = ("index", "kind", "card", "target", "choice", "potion", "cost", "preview")
PREVIEW_FIELDS = ("damage_per_hit", "hits", "block", "draw")
TERMINAL_FIELDS = ("turn", "hp", "max_hp", "block", "energy", "potions")
NORMAL = ("predicted_win", "death")


def only(row, fields):
    return {k: row.get(k) for k in fields}


def public_observation(wire):
    obs = {k: wire[k] for k in OBS_FIELDS}
    for zone in ("deck", "hand", "discard", "exhaust"):
        obs[zone] = [only(card, CARD_FIELDS) for card in obs[zone]]
    obs["enemies"] = [only(e, ("index", "hp", "block", "attack_hits", "intents", "powers"))
                      for e in obs["enemies"]]
    for entity in (obs, *obs["enemies"]):
        entity["powers"] = [only(power, ("id", "amount")) for power in entity["powers"]]
    obs["actions"] = [only(a, ACTION_FIELDS) for a in obs["actions"]]
    for action in obs["actions"]:
        if action["preview"] is not None:
            action["preview"] = only(action["preview"], PREVIEW_FIELDS)
    ids = [a["index"] for a in obs["actions"]]
    if ids != list(range(len(ids))) or sum(a["kind"] == "end_turn" for a in obs["actions"]) != 1:
        raise ValueError("Invalid public menu sequence")
    return {"schema": OBSERVATION, **obs}


def terminal(state, last_action):
    status = state["status"]
    raw = state.get("result") or {}
    evidence = "prediction_only" if raw else "unverified"
    reason = state.get("public_reason") or status
    if status == "truncated":
        reason = state["detail"]
        if reason == "wall_cap":
            status = "timeout"
    if status == "unsupported":
        reason = raw.get("boundary") if raw.get("boundary") not in (None, "None") else "prediction_unsupported"
    if status == "predicted_win" and last_action and last_action["kind"] == "end_turn":
        status, reason = "rule_risk", "E3_ENEMY_SIDE_TERMINAL"
    if status not in (*NORMAL, "unsupported", "truncated", "timeout", "rule_risk", "error"):
        status, reason = "error", "unexpected_solver_status"
    final_view = state.get("terminal_observation")
    return dict(status=status, reason=None if status in NORMAL else reason, evidence=evidence,
                eligible=status in NORMAL, solver_gap_count=len(raw.get("gaps", [])),
                actions=state.get("actions", 0), replays=state.get("transitions", 0),
                observation=only(final_view, TERMINAL_FIELDS) if final_view is not None else None)


def targets(result):
    if not result["eligible"] or result["status"] not in NORMAL:
        return None
    if result["status"] == "death":
        return (0., 0., 0.)
    public = result["observation"]
    slots = public["potions"]
    hp = public["hp"] / public["max_hp"]
    if not 0 < hp <= 1:
        raise ValueError("Invalid HP in qualified victory")
    return (1., hp, sum(p is not None for p in slots) / max(1, len(slots)))


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def save_json(path, value, compress=False):
    data = json_bytes(value)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(gzip.compress(data, mtime=0) if compress else data)
    temporary.replace(path)
