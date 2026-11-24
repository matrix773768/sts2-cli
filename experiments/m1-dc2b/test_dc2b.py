import unittest

from value import CENTERS, expected, payoff, targets, torch


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


if __name__=="__main__":
    unittest.main()
