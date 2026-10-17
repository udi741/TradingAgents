import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from alpha_rnd import success_plan as sp, monitor

class S(unittest.TestCase):
    def test_valid(self):
        p,_=sp.validate({"base_case_value_range":[90,90],
          "success_criteria":"x","profit_realization_plan":"y"},80,74.5)
        self.assertEqual(p["expected_upside_pct"],12.5)
        self.assertAlmostEqual(p["expected_reward_to_risk"],1.82,2)
    def test_missing_fails(self):
        v,e=sp.validate({},80,74.5)
        self.assertIsNone(v); self.assertTrue(e)
    def test_below_entry_fails(self):
        v,e=sp.validate({"base_case_value_range":[208,208],
          "success_criteria":"x","profit_realization_plan":"y"},209.55,164)
        self.assertIsNone(v)
        self.assertTrue(any("<= long entry" in x for x in e))
    def test_upside_realized(self):
        self.assertEqual(sp.upside_realized_pct(80,90,85),50.0)
        self.assertEqual(sp.upside_realized_pct(80,90,92.46),124.6)
    def test_runner_contract(self):
        ok,_=sp.runner_contract_ok({"remaining_thesis":"q3 hold",
          "revised_objective":95,"remaining_upside_pct":12})
        self.assertTrue(ok)
        for bad in ({},{"remaining_thesis":"x"},
                    {"remaining_thesis":"x","revised_objective":95,
                     "remaining_upside_pct":0}):
            ok,w=sp.runner_contract_ok(bad); self.assertFalse(ok)
    def test_ctx_fields(self):
        f=sp.mgmt_context_fields(sp.extract({"target":90}),80,84.52)
        self.assertTrue(f["base_case_reached"] is False)
        self.assertAlmostEqual(f["remaining_upside_pct_to_base"],6.48,1)
        self.assertEqual(f["pct_original_upside_realized"],45.2)
if __name__=="__main__": unittest.main(verbosity=0)
