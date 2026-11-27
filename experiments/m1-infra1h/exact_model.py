"""Reuse frozen singleton G2 results only for identical, completely encoded rows."""
from collections import OrderedDict
import pickle

class ExactModel:
    def __init__(self):
        self.model=None
        self.rows=OrderedDict()
        self.hits=self.misses=0

    def bind(self,controller):
        if self.model is not controller.model:
            self.model=controller.model
            self.rows.clear()
        original=controller.forward
        def forward(rows):
            if len(rows)!=1:return original(rows)
            # Includes dtype, shape, array order, dc_hp, legal action slots,
            # policy ID and encoded public history. Bytes equality resolves hash collisions.
            key=pickle.dumps(rows[0],protocol=5)
            if key in self.rows:
                self.hits+=1
                self.rows.move_to_end(key)
                return self.rows[key]
            self.misses+=1
            values=original(rows)
            if len(self.rows)>=4096:self.rows.popitem(last=False)
            self.rows[key]=values
            return values
        controller.forward=forward

    def save(self,folder):
        import json
        (folder/"infra1h-exact-g2.json").write_text(json.dumps(dict(hits=self.hits,misses=self.misses,capacity=4096)))
