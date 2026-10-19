"""The MCP service layer: calculator dispatch and design-study wrappers.

These exercise :mod:`uav_mcp.service`, which has no dependency on the ``mcp``
package, so they run in the pinned environment as well.
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from uav_mcp import service  # noqa: E402


class TestCalculators(unittest.TestCase):
    def test_every_bundled_calculator_is_listed(self):
        listing = service.list_calculators()
        ids = {row["id"] for row in listing["calculators"]}
        self.assertGreaterEqual(listing["count"], 31)
        self.assertTrue({"WingSizing", "ConstraintDiagram", "ThrustMotorSelection",
                         "BatterySizing"} <= ids)

    def test_category_filter(self):
        rows = service.list_calculators("multirotor")["calculators"]
        self.assertTrue(rows)
        self.assertTrue(all("Multirotor" in r["category"] for r in rows))

    def test_describe_marks_required_inputs(self):
        spec = {i["key"]: i for i in service.describe_calculator("ConstraintDiagram")["inputs"]}
        self.assertTrue(spec["mass"]["required"])
        self.assertFalse(spec["cl_max"]["required"])

    def test_run_accepts_unit_suffixes_and_numbers(self):
        metric = service.run_calculator("WingSizing", {"mass": 2.5, "velocity": 16})
        imperial = service.run_calculator("WingSizing", {"mass": "5.511557 lb", "velocity": "16 m/s"})
        self.assertTrue(metric["ok"])
        self.assertAlmostEqual(metric["outputs"]["Wing Area (S)"]["value"],
                               imperial["outputs"]["Wing Area (S)"]["value"], places=5)

    def test_lookup_by_display_name(self):
        self.assertEqual(service.describe_calculator("wing area sizing")["id"], "WingSizing")

    def test_missing_required_input_is_reported_not_raised(self):
        result = service.run_calculator("WingSizing", {})
        self.assertFalse(result["ok"])
        self.assertIn("required", result["error"])

    def test_unknown_inputs_and_calculators_raise(self):
        with self.assertRaises(ValueError):
            service.run_calculator("WingSizing", {"masss": 2})
        with self.assertRaises(ValueError):
            service.run_calculator("NoSuchTool")

    def test_figures_are_png(self):
        result = service.run_calculator("ConstraintDiagram",
                                        {"mass": 2, "v_stall": 10, "v_cruise": 18})
        self.assertTrue(result["ok"])
        self.assertTrue(result["figures"])
        self.assertTrue(result["figures"][0]["png"].startswith(b"\x89PNG"))


class TestStudies(unittest.TestCase):
    def setUp(self):
        self.study = service.new_study("fixed_wing")
        self.study["max_evaluations"] = 60

    def test_results_are_json_safe(self):
        json.dumps(service.evaluate_design(self.study), allow_nan=False)

    def test_study_accepts_json_text(self):
        result = service.evaluate_design(json.dumps(self.study))
        self.assertTrue(result["result"]["valid"])

    def test_evaluate_matches_engine(self):
        from uavlib.optimization import StudyDefinition, evaluate
        direct = evaluate(StudyDefinition.from_dict(self.study))
        wrapped = service.evaluate_design(self.study)["result"]
        self.assertAlmostEqual(wrapped["metrics"]["takeoff_mass"], direct.metrics["takeoff_mass"])
        self.assertNotIn("mission_history", wrapped)
        self.assertIn("mission_history",
                      service.evaluate_design(self.study, include_history=True)["result"])

    def test_invalid_study_raises(self):
        self.study["objectives"] = []
        with self.assertRaises(ValueError):
            service.evaluate_design(self.study)

    def test_optimize_returns_feasible_candidates_no_heavier_than_baseline(self):
        result = service.optimize_design(self.study, max_candidates=2)
        self.assertEqual(result["evaluations"], 60)
        self.assertTrue(result["candidates"])
        self.assertTrue(all(c["feasible"] for c in result["candidates"]))
        self.assertLessEqual(result["candidates"][0]["metrics"]["takeoff_mass"],
                             result["baseline"]["metrics"]["takeoff_mass"] + 1e-9)
        self.assertNotIn("history", result)

    def test_budget_is_capped(self):
        definition = service.parse_study(self.study)
        definition.max_evaluations = service.MAX_EVALUATIONS + 1
        warnings = []
        service._limit_budget(definition, warnings)
        self.assertEqual(definition.max_evaluations, service.MAX_EVALUATIONS)
        self.assertTrue(warnings)

    def test_sensitivity_elasticity_of_mass_to_wing_area_is_positive(self):
        result = service.sensitivity_analysis(self.study, metrics=["takeoff_mass"])
        self.assertGreater(result["elasticities"]["wing_area"]["takeoff_mass"], 0)
        self.assertEqual(set(result["nominal_metrics"]), {"takeoff_mass"})

    def test_sweep_and_uncertainty(self):
        sweep = service.sweep_design(self.study, {"kind": "grid",
                                                  "axes": {"wing_area": [0.5, 0.7]}})
        self.assertEqual(sweep["samples"], 2)
        uncertainty = service.uncertainty_analysis(
            self.study, {"samples": 5, "inputs": {"cd0": {"distribution": "uniform",
                                                          "lower": 0.03, "upper": 0.04}}})
        self.assertEqual(uncertainty["summary"]["completed_samples"], 5)
        self.assertIn("p50", uncertainty["summary"]["percentiles"]["takeoff_mass"])

    def test_sample_limit(self):
        with self.assertRaises(ValueError):
            service.sweep_design(self.study, {"samples": service.MAX_SAMPLES + 1})

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            saved = service.save_study(self.study, folder)
            loaded = service.load_study(os.path.join(folder, saved["saved_study"]))
        self.assertEqual(loaded, self.study)

    def test_design_space_lists_every_family(self):
        space = service.describe_design_space()
        self.assertEqual(set(space["families"]), set(service.FAMILIES))
        self.assertIn("takeoff_mass", space["families"]["multirotor"]["available_metrics"])

    def test_references_exist(self):
        for topic in service.REFERENCES:
            self.assertTrue(service.get_reference(topic))


if __name__ == "__main__":
    unittest.main()
