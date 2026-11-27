"""Compare singleton and tensor G2 decisions at actual resident frontier barriers."""
from collections import Counter
from pathlib import Path
import json
import numpy as np
from time import perf_counter_ns

class Check:
    def __init__(self):
        self.count=Counter()
        self.examples=[]
        self.max_score=self.max_probability=0.0
    def compare(self,ctrl,inputs,single):
        if len(inputs)<2:return
        start=perf_counter_ns()
        groups=ctrl.score(inputs)
        self.count["batch_time_ns"]+=perf_counter_ns()-start
        self.count["groups"]+=1;self.count["nodes"]+=len(single)
        for i,(a,b) in enumerate(zip(single,groups,strict=True)):
            ds=float(np.max(np.abs(a[0]-b[0])));dp=float(np.max(np.abs(a[1]-b[1])))
            self.max_score=max(self.max_score,ds);self.max_probability=max(self.max_probability,dp)
            self.count["scores_different"]+=ds!=0
            self.count["probabilities_different"]+=dp!=0
            self.count["score_over_0_001"]+=ds>0.001
            self.count["prob_over_0_00001"]+=dp>0.00001
            changed=int(a[0].argmax())!=int(b[0].argmax())
            self.count["argmax_different"]+=changed
            self.count["rank_different"]+=not np.array_equal(np.argsort(-a[0],kind="stable"),np.argsort(-b[0],kind="stable"))
            if changed and len(self.examples)<8:
                self.examples.append(dict(turn=inputs[i][0]["turn"],single=a[0].tolist(),batch=b[0].tolist()))
    def save(self,folder):
        (folder/"infra1h-g2.json").write_text(json.dumps(dict(counts=self.count,max_score=self.max_score,
            max_probability=self.max_probability,examples=self.examples),indent=2))
