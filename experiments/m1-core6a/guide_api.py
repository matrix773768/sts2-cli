"""Public client for the portable CORE-6A bundle. No engine process is needed."""
from .policy import Guide
from .features import Encoder
import numpy as np

class PublicGuide(Guide):
    initial_history=staticmethod(Encoder.initial_history)

    @staticmethod
    def advance_history(history, observation, action_index):
        if not 0<=action_index<len(observation["actions"]):
            raise ValueError("executed action outside public menu")
        action=observation["actions"][action_index]
        encoder=Encoder([])
        history=encoder.update(history,observation,action)
        if action["kind"]=="select_candidate":
            confirm=dict(kind="confirm_selection",index=0,card=None,target=None,choice=None,cost=None)
            selected=observation["decision"]|dict(selected=[action["choice"]])
            history=encoder.update(history,observation|dict(decision=selected,actions=[confirm]),confirm)
        return history

    def proposals(self,observation,history,opening,reference):
        if not 0<=reference<len(observation["actions"]):
            raise ValueError("reference outside public menu")
        scores=self.scores(observation,history,opening)
        order=np.argsort(-scores,kind="stable").tolist()
        if len(order)==1:return order
        menu=observation["actions"]
        if observation["decision"]["phase"]=="choice":return order
        end=next(a["index"] for a in menu if a["kind"]=="end_turn")
        opportunity=any((a.get("preview") or {}).get("draw") or a.get("energy_x") for a in menu)
        extra=opportunity or scores[order[0]]-scores[order[1]]<.55
        return list(dict.fromkeys([*order[:2+int(extra)],reference,end]))

