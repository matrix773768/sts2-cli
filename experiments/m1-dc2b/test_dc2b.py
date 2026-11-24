import unittest
from importlib.util import module_from_spec, spec_from_file_location
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from value import CENTERS, ROOT, expected, payoff, targets, torch


class Tests(unittest.TestCase):
    def test_signed_targets_and_death(self):
        hp=torch.tensor([80,80,80,80])
        end=torch.tensor([82,75,80,0])
        labels=targets(hp,end,end==0)
        self.assertEqual([CENTERS[i-1] for i in labels[:3]],[-2,5,0])
        self.assertEqual(labels[-1].item(),0)
        with self.assertRaises(ValueError):
            targets(torch.tensor([3000]),torch.tensor([1]),torch.tensor([False]))

    def test_distribution_and_terminal(self):
        distances=torch.tensor([0.,20.,100.])
        self.assertTrue(torch.allclose(payoff(distances,torch.tensor([80,80,80])),100-distances))
        prob=torch.zeros(1,len(CENTERS)+1)
        prob[0,1+CENTERS.index(0)]=.5
        prob[0,1+CENTERS.index(20)]=.5
        actual=expected(prob,torch.tensor([999.]),torch.tensor([989.]),torch.tensor([999.]))
        self.assertAlmostEqual(actual.item(),payoff(torch.tensor([10.,30.]),torch.tensor([999])).mean().item())
        self.assertNotAlmostEqual(actual.item(),payoff(torch.tensor([20.]),torch.tensor([999])).item())

    def test_committed_experience_target_can_precede_attempt_cap(self):
        definition = spec_from_file_location("dc2b_stages", Path(__file__).with_name("stages.py"))
        stages = module_from_spec(definition)
        definition.loader.exec_module(stages)
        from tools.training_manager.common import read
        from tools.training_manager.worker import verify_progress

        temp = ROOT / "logs/inf1"
        temp.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=temp, prefix="dc2b-progress-") as directory:
            work = Path(directory) / "stage"
            log = Path(directory) / "progress.json"
            checkpoint = work / "ledger/results.sqlite"

            def run(*_args, **_kwargs):
                checkpoint.parent.mkdir()
                checkpoint.write_bytes(b"committed")
                return {"attempts": 4, "complete": 3}

            args = ["stages.py", "produce", str(work), "--count","6","--target","3","--chunk","4"]
            with (patch.object(sys, "argv", args), patch.dict(os.environ, {"INF1_PROGRESS":str(log), "INF1_STOP":""}),
                  patch.object(stages, "production", return_value={"jobs":list(range(6))}),
                  patch.object(stages, "deploy", return_value=(run, ())), patch.object(stages, "Host", Mock())):
                self.assertEqual(stages.main(), 0)
            progress = verify_progress(work, read(log))
            self.assertEqual((progress["done"], progress["target"]), (3,3))
            self.assertEqual((progress["attempts"], progress["attempt_limit"]), (4,6))


if __name__=="__main__":
    unittest.main()
