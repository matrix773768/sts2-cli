"""Verify the released evidence offline and write an inventory with the measured compute account."""
from collections import Counter
from datetime import datetime, timezone
import argparse
import time

from diagnose import E,H,INFRA,HUMAN,read,gz,s
from panel import sha

def main(write_ledger):
    tick=time.perf_counter()
    policy_ids={a:s.Actor(a).identity("tactical" if a=="v2" else a,32)["id"]
                for a in ("g2","v2","low","direct")}
    roots=read(E/"panel.json")
    derived=read(E/"results.json")
    assert len({r["key"] for r in roots["roots"]})==40
    assert {r["behavior"] for r in roots["roots"]}=={policy_ids["low"]}
    assert sha(INFRA/"experiments/m1-core5a/evidence/v2.pt")=="d439444a1a9ca9bc8864988e488f720f71b379844b30ddb112bdd8f0ddcfcbbb"
    n=Counter(); failures=Counter(); sources=Counter()
    for root in roots["roots"]:
        key=root["id"]
        data=gz(E/(key+".gz"))
        sources[root["source"]]+=1
        assert data["selected"]["g2"]==data["g2"][0]
        assert sorted(data["g2"])==sorted(data["guide_rank"])==list(range(len(data["menu"])))
        for arm in ("low","h5"):
            for c in data["candidates"][arm]:
                graph=data["graphs"][c]
                mass=graph["q"]["coverage"]
                assert abs(sum(graph["law"].values())-mass)<1e-7
                assert abs(mass+sum(graph["q"]["gaps"].values())-1)<1e-7
                assert abs(sum(graph["opening_loss_mass"].values())+graph["death_mass"]-mass)<2e-5
                assert (graph["q"]["value"] is None)==bool(graph["q"]["gaps"])
                n[arm+"_options"]+=1
        for row in data.get("worlds",[]):
            prefix="original" if row["seed"] is None else "reordered"
            n[prefix+"_attempts"]+=1
            n[prefix+"_complete"]+=int(all(z["status"] in ("Victory","Defeat") for z in row["sides"].values()))
            for z in row["sides"].values():
                if z["status"]=="failed":
                    assert "utility" not in z
                    failures[z["reason"]]+=1
                else:
                    assert z["terminal"]["hp"]>0 if z["status"]=="Victory" else z["terminal"]["hp"]==0
        if key in HUMAN:
            for row in gz(E/(key+"-witness.gz"))["rows"]:
                if "native" in row:
                    assert row["native"]["status"]=="matched"
                    n["native_matched"]+=1
    assert [n[k] for k in ("original_attempts","original_complete","reordered_attempts","reordered_complete","native_matched")]==[16,15,80,56,26]
    assert derived["roots"]["B2"]["comparisons"][-1]["mean"]==128.5
    seconds=dict(panel=roots["seconds"],human=read(E/"human-ledger.json")["seconds"],
                 expanded=read(E/"expanded-ledger.json")["seconds"],native_witness=read(E/"witness-ledger.json")["seconds"],
                 low_suffix_and_draw=gz(E/"sensitivity.gz")["seconds"],representation=gz(E/"representation.gz")["seconds"],
                 gate_control=gz(E/"gate.gz")["seconds"],archive_join=derived["seconds"])
    # The local lifecycle was captured before retry. Preserve its receipt so independent verification
    # does not require an old private transport directory.
    fail_receipt=read(E/"retry-receipt.json")
    seconds["failed_checkpoint_attempt_host"]=fail_receipt["duration_seconds"]
    seconds["native_catalog_build_window"]=round(fail_receipt["catalog_window_seconds"],2)
    files={p.name:sha(p) for p in sorted(E.iterdir()) if p.is_file() and p.name!="ledger.json"}
    if not write_ledger:
        ledger=read(E/"ledger.json")
        assert ledger["evidence_sha256"]==files
        assert ledger["policy_ids"]==policy_ids and ledger["counts"]==n
        assert ledger["failed_sides"]==failures and ledger["root_sources"]==sources
        assert ledger["accounted_upper_seconds"]<3600
        print(f"{len(files)} evidence files verified, {len(roots['roots'])} roots, {n['native_matched']} native matches")
        return
    seconds["evidence_verification"]=time.perf_counter()-tick
    wall=(datetime.now(timezone.utc).timestamp()-(H/"protocol.md").stat().st_mtime)
    from panel import save
    save(E/"ledger.json",dict(schema="core6b1.audit.v1",workers=1,policy_ids=policy_ids,counts=n,failed_sides=failures,
         root_sources=sources,measured_seconds=seconds,sum_seconds=sum(seconds.values()),
         ancillary_allowance_seconds=120,accounted_upper_seconds=sum(seconds.values())+120,
         protocol_to_verification_wall_seconds=wall,evidence_sha256=files))
if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-ledger",action="store_true",help="Seal a newly produced evidence set")
    main(parser.parse_args().write_ledger)
