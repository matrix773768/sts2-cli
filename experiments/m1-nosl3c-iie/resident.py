"""Recycle independent native auditors only after certified map settlement."""
from contextlib import ExitStack
from threading import Lock, local
from time import monotonic, perf_counter
from types import FunctionType

from terminal_contract import targets


class Auditors:
    def __init__(self, limit):
        self.limit = limit
        self.local = local()
        self.lanes = []
        self.lock = Lock()

    def close(self):
        for lane in self.lanes:
            lane.close()

    def audit(self, output, versions, spec, row):
        if not self.limit or row["feedback"]["status"] not in ("predicted_win", "death"):
            return targets.certify(output, versions, spec, row)
        lane = getattr(self.local, "lane", None)
        if lane is None:
            lane = self.local.lane = Lane()
            with self.lock:
                self.lanes.append(lane)
        index = 0
        reused = False

        def open_pair(out, stack, ver):
            nonlocal index, reused
            index += 1
            if index == 1:
                return targets.open_worker(out, stack, ver)
            reused = lane.game is not None and lane.game.deadline - monotonic() >= 20
            if not reused:
                lane.close()
                lane.stack = ExitStack()
                lane.game = targets.open_worker(out, lane.stack, ver)
            lane.count += 1
            return lane.game

        original = targets.certify
        replay = FunctionType(original.__code__, original.__globals__ | {"open_worker": open_pair})
        try:
            result = replay(output, versions, spec, row)
        except BaseException:
            lane.close()
            raise
        started = perf_counter()
        if result["status"] == "admissible_predicted_win" and lane.count < self.limit:
            try:
                lane.retire()
                retirement = "settled"
            except (targets.BANK.f1.i2.StopRun, ValueError, KeyError, OSError, RuntimeError) as error:
                lane.close()
                retirement = "settlement_failed: " + str(error).splitlines()[0][:160]
        else:
            lane.close()
            retirement = "closed"
        return result | dict(auditor_reused=reused, retirement=retirement,
                             retirement_ms=(perf_counter() - started)*1000)


class Lane:
    def __init__(self):
        self.game = self.stack = None
        self.count = 0

    def close(self):
        if self.stack is not None:
            self.stack.close()
        self.game = self.stack = None
        self.count = 0

    def retire(self):
        game = self.game
        if game.request("action", action="skip_card_reward")["decision"] != "map_select":
            raise ValueError("No settled map after native victory")
        game.request("i1_release")
        game.request("f1_3c_release")
        if game.request("b1a_reset")["type"] != "reset":
            raise ValueError("Guarded reset rejected")
        if game.request("b1a_profile")["value"] != game.request("b1b_initial_profile")["value"]:
            raise ValueError("Failed to restore initial profile")
