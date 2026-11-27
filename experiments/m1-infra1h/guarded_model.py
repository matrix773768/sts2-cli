"""Optional measured numerical contract for reference argmax. V2 remains frozen."""
from collections import Counter
import json
import numpy as np

class Guarded:
    tolerance=0.001
    def __init__(self):
        self.counts=Counter()
    def choose(self,controller,inputs):
        if len(inputs)<2:return [int(controller.score([v])[0][0].argmax()) for v in inputs]
        self.counts["frontiers"]+=1
        result=[]
        for value,(scores,_) in zip(inputs,controller.score(inputs),strict=True):
            if not np.isfinite(scores).all():raise ValueError("Non-finite G2 scores")
            if len(scores)>1:
                top=np.partition(scores,-2)[-2:]
                if top.max()-top.min()<=2*self.tolerance:
                    scores=controller.score([value])[0][0]
                    self.counts["singleton_margin"]+=1
            self.counts["nodes"]+=1
            result.append(int(scores.argmax()))
        return result
    def save(self,folder):
        (folder/"infra1h-guarded-g2.json").write_text(json.dumps(dict(counts=self.counts,abs_score_tolerance=self.tolerance)))
