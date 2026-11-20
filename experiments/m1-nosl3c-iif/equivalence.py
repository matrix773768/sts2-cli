"""Conservative semantic equivalence for an unrecoverable enemy-turn death."""
import re
from hashlib import sha256

VERSION = "sts2.nosl.iif.enemy-death-window.v1"
GAME = "62ecbe91093e1fa862de4329aac865209dcb297804caf0f0520d92d8c0b4a9c3"
SOLVER = "6d36540518549768f66cc6f44bdf6c20ab44a7243158ba5c8abc3d7f13030293"
COUNTERS = re.compile(r"(?<=;)Y=(\d+/\d+/\d+/\d+);FlameHp=(\d+);AttackStarts=(\d+)(?=;)")
KEYS = re.compile(r"(?:^|;)(Y|AttackStarts)=")


def stamp(text):
    return sha256(text.encode("utf-8")).hexdigest()


def split(text):
    matches = list(COUNTERS.finditer(text))
    if len(matches) != 1 or sorted(KEYS.findall(text)) != ["AttackStarts", "Y"]:
        return None
    m, = matches
    return (m[1], m[3]), text[:m.start()] + f"Y=<window>;FlameHp={m[2]};AttackStarts=<window>" + text[m.end():]


def qualifies(record, feedback, prefix, predicted_text, native_text, closed):
    engine = record["versions"]
    if (engine["game_sha256"], engine["solver_sha256"], engine["coreclr"]) != (GAME, SOLVER, "9.0.7"):
        return False
    pos = record.get("position")
    before = record.get("native_before", {})
    after = record.get("native_after", {})
    prediction = record.get("prediction", {})
    final = prediction.get("terminal_observation") or {}
    player = after.get("player", {})
    previous = record.get("previous") or {}
    if (record.get("reason") != "enemy_stage_death_boundary" or not closed or not isinstance(pos, int)
            or pos < 1 or pos != feedback["actions"] - 1 or prediction.get("actions") != feedback["actions"]
            or previous.get("position") != pos-1 or stamp(prefix) != previous.get("stamp")
            or record["path"][-1]["kind"] != "end_turn" or before.get("decision") != "combat_play"
            or before.get("round") != final.get("turn")
            or after.get("decision") != "game_over" or after.get("victory") is not False
            or prediction.get("status") != "death" or feedback["status"] != "death"
            or not feedback["eligible"] or final != feedback["observation"]
            or prediction.get("audit_stamp") != stamp(predicted_text)
            or record.get("native_frame", {}).get("terminal") is not False
            or predicted_text == native_text):
        return False
    native_frame = record["native_frame"]["state"][0]
    if (native_frame["exact_continuation_state"] != native_text or player.get("hp") != 0 or final["hp"] != 0
            or player.get("max_hp") != final["max_hp"] or player.get("block") != final["block"]
            or player.get("gold") != prediction["result"]["gold"] or player.get("potions")
            or any(final["potions"])):
        return False
    p, n, prior = (split(t) for t in (predicted_text, native_text, prefix))
    return (p is not None and n is not None and prior is not None
            and p[1] == n[1] and n[0] == ("0/0/0/0", "0") and p[0] == prior[0])
