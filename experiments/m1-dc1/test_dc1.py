import unittest

import numpy as np

from dc_common import config
from dc_metrics import describe, paired
from dc_roots import manifest, world
from dc_utility import LOSS_CENTERS, NET_CENTERS, bin_center, labels, loss_curve, risk_order


def result(status, hp, cumulative):
    return dict(status=status, complete=status != "truncated", family="family",
                root=dict(hp=50,max_hp=80), length=3, cumulative_loss=cumulative,
                terminal=dict(hp=hp,max_hp=83,turn=2,potions=[],gold=99))


class ContractTests(unittest.TestCase):
    def test_damage_and_healing_accounting(self):
        restored = result("predicted_win",54,13)
        value = labels(restored)
        self.assertEqual((value["net_loss"],value["cumulative_loss"],value["max_hp_delta"]),(-4,13,3))
        self.assertEqual(value["hp_credit"],17)
        self.assertIsNone(value["healing"])
        self.assertEqual(bin_center(-4,NET_CENTERS), -4)
        self.assertIsNone(bin_center(-4, LOSS_CENTERS))
        self.assertIsNone(bin_center(9000, LOSS_CENTERS))
        self.assertEqual([bin_center(i, LOSS_CENTERS) for i in range(21)], list(range(21)))

    def test_survival_constraint_and_fallback(self):
        self.assertEqual(risk_order(np.array([.01,.03,.07]),np.array([20,40,50]),.05).tolist(), [1,0,2])
        self.assertEqual(risk_order(np.array([.08,.09]),np.array([10,40]),.05).tolist(), [0,1])
        self.assertAlmostEqual(loss_curve(1e-5)/1e-5,1,places=5)

    def test_paired_survival_and_missingness(self):
        loss = result("death",0,51)
        win = result("predicted_win",45,10)
        trunc = result("truncated",50,None)
        stats = paired(((loss,win),(win,trunc),(win,win)))
        self.assertEqual(stats["joint_wins"],1)
        self.assertEqual(stats["joint_complete"],2)
        self.assertAlmostEqual(stats["death_delta"],-1/3)
        summary = describe((loss,win,trunc))
        self.assertAlmostEqual(summary["win_at_or_below"]["5"],1/3)
        self.assertEqual(summary["net_quantiles"]["p90"],50)

    def test_repeat_seeds_are_stable_and_partitioned(self):
        spec, cfg = dict(hp=70), config()
        first = world(spec,cfg,"a",0)
        self.assertEqual(first,world(spec,cfg,"a",0))
        self.assertEqual(spec,dict(hp=70))
        self.assertEqual(len({x["seed"] for x in (first,world(spec,cfg,"a",1),
            world(spec,cfg,"b",0),world(spec,cfg,"a",0,"diagnostic"))}),4)
        self.assertEqual(manifest(cfg,"stage",[] )["purpose"],"stage")


if __name__ == "__main__":
    unittest.main()
