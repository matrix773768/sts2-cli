"""Death certification adds an outcome contract to the unchanged exact IID replay."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "m1-nosl3c-iid"))
import targets

VERSION = "sts2.nosl.iie.exact-terminal.v1"


def death_verified(record, feedback):
    # IID reaches terminal_not_locked only after replaying the complete route,
    # including an exact match of the final native continuation stamp.
    if record.get("reason") != "terminal_not_locked" or record.get("boundaries", 0) < 1:
        return False
    live, predicted = record["native_after"], record["prediction"]
    final, result = predicted.get("terminal_observation", {}), predicted.get("result", {})
    path = record.get("path", [])
    if (not path or len(path) != feedback["actions"] or predicted.get("actions") != feedback["actions"]
            or path[-1]["kind"] not in ("end_turn", "play_card", "confirm_selection")):
        return False
    player = live.get("player", {})
    return (live.get("decision") == "game_over" and live.get("victory") is False
            and predicted.get("status") == feedback["status"] == "death"
            and bool(predicted.get("audit_stamp")) and final == feedback["observation"]
            and final.get("hp") == player.get("hp") == 0
            and final.get("max_hp") == player.get("max_hp")
            and final.get("block") == player.get("block")
            and result.get("gold") == player.get("gold")
            and not any(final.get("potions", [])) and not player.get("potions"))


def certify(output, versions, spec, row, audit=None):
    evidence = (audit or targets.certify)(output, versions, spec, row)
    if death_verified(evidence, row["feedback"]):
        evidence.update(status="admissible_death", terminal_verified=True, reason=None,
                        death_contract=VERSION, native_terminal_stamp=evidence["prediction"]["audit_stamp"])
    evidence["terminal_contract"] = VERSION
    final = row["feedback"].get("observation") or {}
    accounting = row["feedback"].pop("engine_accounting", {})
    result = evidence.get("prediction", {}).get("result", {}) or accounting
    hp = final.get("hp")
    row["hp_accounting"] = dict(
        initial_hp=spec["hp"], initial_max_hp=spec["max_hp"], final_hp=hp,
        final_max_hp=final.get("max_hp"), net_loss=None if hp is None else max(0, spec["hp"]-hp),
        excess_healing=None if hp is None else max(0,hp-spec["hp"]),
        max_hp_change=None if not final else final["max_hp"]-spec["max_hp"],
        cumulative_hp_loss=result.get("cumulative_loss"), received_damage=None,
        voluntary_loss=None, healing=None, turns=final.get("turn"), decisions=len(row["transitions"]))
    return evidence
