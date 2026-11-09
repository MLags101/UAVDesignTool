"""
Compressible Flow Calculator

Exact gas-dynamic relations for a calorically perfect gas: isentropic flow,
normal shocks, oblique shocks (weak or strong), Prandtl-Meyer expansions and
Taylor-Maccoll cone flow. These are the building blocks for inlet ramps,
nose cones, shock-expansion airfoils and nozzle sizing.
"""

import math

from uavlib import compressible, report, units

MODES = ["Isentropic", "Normal shock", "Oblique shock", "Prandtl-Meyer expansion",
         "Cone (Taylor-Maccoll)"]

TOOL_METADATA = {
    "name": "Compressible Flow",
    "category": "Supersonic / Reference",
    "description": (
        "Isentropic, normal-shock, oblique-shock, expansion-fan and cone-flow "
        "properties at any Mach number (NACA Report 1135 relations)."
    ),
    "inputs": [
        {"key": "mode", "label": "Calculation", "type": "choice", "choices": MODES,
         "default": "Oblique shock"},
        {"key": "mach", "label": "Upstream Mach Number", "type": "number", "default": "2.0"},
        {"key": "angle", "label": "Deflection / Turn / Cone Half-Angle", "unit": "deg",
         "type": "number", "default": "10",
         "help": "Wedge deflection for oblique shocks, turning angle for expansions, "
                 "half-angle for cones. Ignored for isentropic and normal shock."},
        {"key": "branch", "label": "Oblique Shock Solution", "type": "choice",
         "choices": ["Weak", "Strong"], "default": "Weak"},
        {"key": "gamma", "label": "Ratio of Specific Heats", "type": "number", "default": "1.4"},
    ],
}


def run(inputs):
    try:
        mode = inputs.get("mode") or "Oblique shock"
        mach = units.positive(inputs, "mach", "", "Mach number")
        angle = units.optional(inputs, "angle", "deg", 10.0)
        gamma = units.positive(inputs, "gamma", "", "Gamma", 1.4)
        if not 1.0 < gamma < 1.7:
            raise ValueError("Gamma should lie between 1.0 and 1.7.")
        r = report.Report(f"Compressible Flow: {mode}")
        r.value("Upstream Mach", mach, "", 4)
        outputs = {}

        if mode == "Isentropic":
            values = compressible.isentropic(mach, gamma)
            r.section("Ratios to Stagnation Conditions")
            for label, value in values.items():
                r.value(label.replace("_deg", " (deg)"), value, "", 5)
            outputs = {"p/p0": {"value": values["p/p0"], "unit": ""},
                       "T/T0": {"value": values["T/T0"], "unit": ""}}
        elif mode == "Normal shock":
            shock = compressible.normal_shock(mach, gamma)
            r.section("Downstream / Upstream")
            for label, value in shock.items():
                r.value(label, value, "", 5)
            outputs = {"Downstream Mach": {"value": shock["M2"], "unit": ""},
                       "Total Pressure Recovery": {"value": shock["p02/p01"], "unit": ""}}
        elif mode == "Oblique shock":
            strong = inputs.get("branch") == "Strong"
            theta_max = math.degrees(compressible.max_deflection(mach, gamma))
            shock = compressible.oblique_shock(mach, math.radians(angle), strong, gamma)
            r.value("Deflection", angle, "deg", 3)
            r.value("Detachment deflection", theta_max, "deg", 3)
            r.section("Shock")
            r.value("Shock angle", shock["beta_deg"], "deg", 3)
            r.value("Normal Mach (upstream)", shock["Mn1"], "", 4)
            r.value("Downstream Mach", shock["M2"], "", 4)
            r.value("p2/p1", shock["p2/p1"], "", 4)
            r.value("T2/T1", shock["T2/T1"], "", 4)
            r.value("rho2/rho1", shock["rho2/rho1"], "", 4)
            r.value("p02/p01 (recovery)", shock["p02/p01"], "", 5)
            if shock["M2"] < 1:
                r.warn("Flow behind this shock is subsonic.")
            outputs = {"Shock Angle": {"value": shock["beta_deg"], "unit": "deg"},
                       "Downstream Mach": {"value": shock["M2"], "unit": ""},
                       "Pressure Ratio": {"value": shock["p2/p1"], "unit": ""}}
        elif mode == "Prandtl-Meyer expansion":
            fan = compressible.expansion(mach, math.radians(angle), gamma)
            r.value("Turning angle", angle, "deg", 3)
            r.value("nu upstream", math.degrees(compressible.prandtl_meyer(mach, gamma)), "deg", 3)
            r.section("Downstream")
            r.value("Mach", fan["M2"], "", 4)
            r.value("p2/p1", fan["p2/p1"], "", 5)
            r.value("T2/T1", fan["T2/T1"], "", 5)
            outputs = {"Downstream Mach": {"value": fan["M2"], "unit": ""},
                       "Pressure Ratio": {"value": fan["p2/p1"], "unit": ""}}
        elif mode == "Cone (Taylor-Maccoll)":
            cone = compressible.cone_flow(mach, math.radians(angle), gamma)
            wedge = compressible.oblique_shock(mach, math.radians(angle), gamma=gamma)
            r.value("Cone half-angle", angle, "deg", 3)
            r.section("Cone Flow")
            r.value("Shock angle", cone["beta_deg"], "deg", 3)
            r.value("Surface Mach", cone["surface_mach"], "", 4)
            r.value("Surface p/p1", cone["pc/p1"], "", 4)
            r.value("Surface pressure coefficient", cone["cp"], "", 4)
            r.value("Recovery through shock", cone["p02/p01"], "", 5)
            r.note(f"A {angle:g} deg wedge would have a {wedge['beta_deg']:.2f} deg shock and "
                   f"p/p1 = {wedge['p2/p1']:.3f}: cones relieve three-dimensionally.")
            outputs = {"Shock Angle": {"value": cone["beta_deg"], "unit": "deg"},
                       "Surface Cp": {"value": cone["cp"], "unit": ""}}
        else:
            raise ValueError(f"Unknown calculation '{mode}'.")
        return report.result(r, outputs=outputs)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
