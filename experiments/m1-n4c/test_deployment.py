import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from types import SimpleNamespace
import deploy
from assess import harm_upper, load_rows
from pilot_protocol import cohort, design, gate, jobs, write

class DeploymentTests(unittest.TestCase):
    def test_gate_and_frequency(self):
        h=dict(decision={"phase":"combat"},turn=2,hp=24,block=0,energy=2,
               enemies=[{"attack_hits":[5,5]}],actions=[{"kind":"play_card","card":i} for i in (0,1)])
        self.assertTrue(gate(h))
        self.assertFalse(gate(h|dict(actions=[h["actions"][0]]*2)))
        self.assertFalse(gate(h|dict(block=10)))
        self.assertFalse(deploy.eligible("plan_gate",h,2,{2}))
        self.assertTrue(deploy.eligible("plan_all",h,2,{2}))
        self.assertFalse(deploy.eligible("plan_once",h,1,set()))
        self.assertFalse(deploy.eligible("q_budget",h,4,set()))
        self.assertTrue(deploy.eligible("plan_budget",h,3,{1}))

    def test_legal_endpoint_semantics(self):
        h=dict(hp=20,block=0,enemies=[{"hp":10}],actions=[{"kind":"play_card"}])
        before=dict(hp=18,block=3,enemies=[{"hp":2}],actions=[{"kind":"end_turn"}])
        s=SimpleNamespace(index=0,observation=h)
        t=SimpleNamespace(index=0,observation=before)
        ends=[(dict(kind="end_play_a"),[s,t]),(dict(kind="random"),[s]),
              (dict(kind="victory",public={"hp":16}),[s])]
        lane=Mock()
        lane.request.return_value=dict(transitions=7,boundaries=[])
        with patch.object(deploy,"extract",return_value=({}, {},ends,{})):
            paths,info=deploy.options(lane,Mock(),h,24)
        self.assertEqual({(p["kind"],p["hp"],p["damage"]) for p in paths},
                         {("victory",16,10),("end_play_a",18,8)})
        self.assertEqual(info["transitions"],7)
        self.assertTrue(lane.request.call_args.kwargs["public_run"])

    def test_no_false_safety_at_small_n(self):
        self.assertGreater(harm_upper(0,0,32),.05)
        self.assertGreater(harm_upper(1,0,64),harm_upper(0,0,64))

    def test_family_isolation_and_repair(self):
        js=jobs()
        fam=lambda split:{j["family"] for j in js if j["split"]==split}
        self.assertFalse(fam("dev")&fam("confirm"))
        trained={j["family"] for j in design.jobs() if j["split"]!="confirm"}|{j[3] for j in cohort.plan() if j[2]!="confirm"}
        self.assertFalse(fam("confirm")&trained)
        self.assertEqual(len(fam("confirm")),64)
        self.assertEqual(sum(j["domain"]=="natural" for j in js),72)
        j=next(j for j in js if deploy.repaired(j))
        repl=deploy.repaired(j)
        self.assertIn("HEAVY_BLADE",[c["id"] for c in j["spec"]["deck"][5:10]])
        self.assertIn("HEMOKINESIS",[c["id"] for c in repl["spec"]["deck"][5:10]])
        self.assertEqual(j["family"],repl["family"])

    def test_merging_requires_matching_world(self):
        with TemporaryDirectory() as temp:
            dirs=[]
            for i in range(2):
                d=Path(temp)/str(i)
                d.mkdir()
                dirs.append(d)
                write(d/"run.json",dict(seconds=1))
                write(d/"001.json.gz",dict(domain="natural",family="A",stop="complete",anchor=None,
                    worlds=[dict(world={"seed":str(i)},public="same",outcomes={str(i):{}})]))
            with self.assertRaisesRegex(ValueError,"pairing"):
                load_rows(dirs)

if __name__=="__main__":
    unittest.main()
