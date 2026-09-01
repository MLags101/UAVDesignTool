"""Every bundled tool must load, validate and run.

Also pins the regression values for the three defects this overhaul corrected,
so they cannot silently return.
"""

import glob
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from uav_app.tool_base import ToolError, ToolManager, normalise_result  # noqa: E402

TOOL_DIRS = ["Fixed Wing Tools", "Multicopter Tools", "Shared Tools"]


def tool_files():
    paths = []
    for folder in TOOL_DIRS:
        paths.extend(sorted(glob.glob(os.path.join(ROOT, folder, "*.py"))))
    paths.append(os.path.join(ROOT, "template_tool.py"))
    paths.append(os.path.join(ROOT, "MassToWeight.py"))
    return [p for p in paths if os.path.exists(p)]


def default_inputs(metadata):
    """Build a plausible input set from each tool's declared defaults."""
    values = {}
    for spec in metadata["inputs"]:
        if spec["default"]:
            values[spec["key"]] = spec["default"]
        elif spec["type"] == "choice":
            values[spec["key"]] = spec["choices"][0]
        else:
            values[spec["key"]] = ""
    return values


class TestAllToolsLoad(unittest.TestCase):
    def test_at_least_the_expected_tools_exist(self):
        self.assertGreaterEqual(len(tool_files()), 11)

    def test_every_tool_loads_and_validates(self):
        for path in tool_files():
            with self.subTest(tool=os.path.basename(path)):
                tool, metadata = ToolManager.load_tool_from_file(path)
                self.assertTrue(metadata["name"])
                self.assertIsInstance(metadata["inputs"], list)
                for spec in metadata["inputs"]:
                    self.assertIn(spec["type"],
                                  ("text", "number", "choice", "file"))

    def test_every_tool_runs_on_its_defaults(self):
        """A tool must return output rather than raising, even when underfed."""
        for path in tool_files():
            with self.subTest(tool=os.path.basename(path)):
                tool, metadata = ToolManager.load_tool_from_file(path)
                result = normalise_result(tool.run(default_inputs(metadata)))
                self.assertTrue(result["text"].strip(),
                                "tool produced no output text")

    def test_every_tool_handles_all_blank_input(self):
        """Blank fields must produce a readable message, never a traceback."""
        for path in tool_files():
            with self.subTest(tool=os.path.basename(path)):
                tool, metadata = ToolManager.load_tool_from_file(path)
                blanks = {spec["key"]: "" for spec in metadata["inputs"]}
                result = normalise_result(tool.run(blanks))
                self.assertTrue(result["text"].strip())
                self.assertNotIn("Traceback", result["text"])

    def test_every_tool_handles_garbage_input(self):
        for path in tool_files():
            with self.subTest(tool=os.path.basename(path)):
                tool, metadata = ToolManager.load_tool_from_file(path)
                garbage = {spec["key"]: "not a number"
                           for spec in metadata["inputs"]
                           if spec["type"] != "choice"}
                for spec in metadata["inputs"]:
                    if spec["type"] == "choice":
                        garbage[spec["key"]] = spec["choices"][0]
                result = normalise_result(tool.run(garbage))
                self.assertNotIn("Traceback", result["text"])

    def test_rejects_a_module_that_is_not_a_tool(self):
        path = os.path.join(ROOT, "uavlib", "units.py")
        with self.assertRaises(ToolError):
            ToolManager.load_tool_from_file(path)


def load_tool(name):
    for path in tool_files():
        if os.path.basename(path) == name:
            return ToolManager.load_tool_from_file(path)
    raise AssertionError(f"{name} not found")


class TestCorrectedDefects(unittest.TestCase):
    """The three numerical defects this overhaul fixed, pinned by value."""

    def test_spiral_parameter_uses_degrees(self):
        # Trainer: lv 0.6 m, b 1.5 m, dihedral 5 deg, CL 0.6 -> B = 3.33.
        # The defective version converted to radians and returned 0.058.
        tool, _ = load_tool("SpiralParameter.py")
        result = normalise_result(tool.run({
            "l_v": "0.6", "dihedral": "5", "span": "1.5", "cl": "0.6",
            "target_b": "5"}))
        b = result["outputs"]["Spiral Parameter B"]["value"]
        self.assertAlmostEqual(b, 3.3333, places=3)

    def test_spiral_parameter_can_report_stable(self):
        """The defective version could never return a stable verdict."""
        tool, _ = load_tool("SpiralParameter.py")
        result = normalise_result(tool.run({
            "l_v": "0.9", "dihedral": "8", "span": "1.5", "cl": "0.5",
            "target_b": "5"}))
        self.assertIn("SPIRALLY STABLE", result["text"])

    def test_control_surface_tau_is_a_fraction(self):
        # cf/c = 0.25 -> inviscid 0.609, viscous 0.487.
        # The defective version returned 1.218.
        tool, _ = load_tool("ControlSurfaceEstimator.py")
        result = normalise_result(tool.run({
            "surface": "Aileron", "span": "1.5", "area": "0.3",
            "root_chord": "0.2", "taper": "1.0", "y_inboard": "0.375",
            "y_outboard": "0.75", "chord_fraction": "0.25",
            "deflection": "20", "velocity": "15", "altitude": "0",
            "horn_length": "15"}))
        tau = result["outputs"]["Flap Effectiveness (tau)"]["value"]
        self.assertLessEqual(tau, 1.0)
        self.assertAlmostEqual(tau, 0.487, places=2)

    def test_control_surface_area_uses_chord_fraction(self):
        """Area must scale with the chord fraction, which it previously ignored."""
        tool, _ = load_tool("ControlSurfaceEstimator.py")
        base = dict(surface="Aileron", span="1.5", area="0.3", root_chord="0.2",
                    taper="1.0", y_inboard="0.375", y_outboard="0.75",
                    deflection="20", velocity="15", altitude="0",
                    horn_length="15")
        quarter = normalise_result(tool.run({**base, "chord_fraction": "0.25"}))
        half = normalise_result(tool.run({**base, "chord_fraction": "0.50"}))
        area_quarter = quarter["outputs"]["Aileron Area"]["value"]
        area_half = half["outputs"]["Aileron Area"]["value"]
        self.assertAlmostEqual(area_half / area_quarter, 2.0, places=6)
        # 0.375 m of span at 0.2 m chord and 25% = 0.01875 m^2.
        self.assertAlmostEqual(area_quarter, 0.01875, places=6)

    def test_control_surface_rejects_station_beyond_semispan(self):
        tool, _ = load_tool("ControlSurfaceEstimator.py")
        result = normalise_result(tool.run({
            "surface": "Aileron", "span": "1.5", "area": "0.3",
            "root_chord": "0.2", "taper": "1.0", "y_inboard": "0.375",
            "y_outboard": "1.2", "chord_fraction": "0.25", "deflection": "20",
            "velocity": "15", "altitude": "0", "horn_length": "15"}))
        self.assertIn("beyond the semi-span", result["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
