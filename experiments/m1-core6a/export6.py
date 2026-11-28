"""Package the exact scorer, released mechanism catalog and history adapter without a simulator."""
import gzip
import subprocess
import sys
import tempfile
import time
import zipfile
import numpy as np
from common6 import *
from policy6 import Guide

def main():
    tick=time.perf_counter()
    frozen=read(E/"picked.json")
    weights=E/(frozen["name"]+".pt")
    source=(HERE/"policy6.py").read_text("utf8")
    old="from common6 import public_summary, powers, token, variant, torch"
    assert source.count(old)==1
    source=source.replace(old,"import torch\nfrom .features import public_summary, powers, token, variant")
    feature=INFRA/"experiments/m1-pre1/features.py"
    cards=INFRA/"experiments/m1-n2e/cards.json"
    bundle=E/"public-guide.zip"
    with zipfile.ZipFile(bundle,"w",compression=zipfile.ZIP_DEFLATED) as out:
        out.writestr("core6a/policy.py",source)
        out.writestr("core6a/__init__.py","from .guide_api import PublicGuide\n")
        out.write(HERE/"guide_api.py","core6a/guide_api.py")
        out.write(feature,"core6a/features.py")
        out.write(cards,"m1-n2e/cards.json")
        out.write(weights,"guide.pt")
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        folder=Path(tmp)
        with zipfile.ZipFile(bundle) as z:z.extractall(folder)
        sample=next(read_rows(WORK/"dev-v2-0/public.gz"))["segment"]["steps"]
        record=read(HERE.parent/"m1-core5g/evidence/dev-battles.json")[0]
        opening={k:record["spec"][k] for k in ("hp","max_hp")}
        menus=[(choice_b(s["observation"]["facts"],s["observation"]) if s["observation"]["status"]=="choice" else public_b(s["observation"]["facts"]),s["index"]) for s in sample]
        actor=Models(); guide=Guide(weights); memory=actor.g2.encoder.initial_history(); expected=[]
        for h,i in menus:
            expected.append(guide.scores(h,memory,opening).tolist())
            memory=actor.advance(memory,h,h["actions"][i])
        save(folder/"fixture.json",dict(menus=menus,opening=opening,expected=expected,memory=memory.tolist()))
        check="""import json,sys,numpy as np
sys.path.insert(0,sys.argv[1])
from core6a import PublicGuide
p=PublicGuide('guide.pt')
data=json.load(open('fixture.json'))
history=p.initial_history()
for (obs,action),scores in zip(data['menus'],data['expected'],strict=True):
    np.testing.assert_allclose(p.scores(obs,history,data['opening']),scores,atol=4e-5)
    assert set(p.proposals(obs,history,data['opening'],0))<=set(range(len(scores)))
    history=p.advance_history(history,obs,action)
np.testing.assert_allclose(history,data['memory'],atol=1e-6)
try:
    p.proposals(obs,history,data['opening'],-1)
except ValueError:
    pass
else:
    raise AssertionError('invalid reference accepted')
assert 'hot_produce' not in sys.modules
"""
        subprocess.run([sys.executable,"-I","-c",check,str(folder)],check=True,cwd=folder)
    save(E/"portable.json",dict(sha256=sha(bundle),weight=sha(weights),features=sha(feature),catalog=sha(cards),
                                menus=len(menus),seconds=time.perf_counter()-tick))
if __name__=="__main__":main()
