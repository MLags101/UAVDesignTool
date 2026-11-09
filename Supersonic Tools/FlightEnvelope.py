"""
Flight Envelope

Mach-altitude envelope bounded by lift (stall), thrust (Ps = 0), maximum
dynamic pressure, skin temperature and the Mach 2 model ceiling. Each
altitude reports what sets its limits, and where a transonic thrust gap
splits the envelope.
"""

from uavlib import aerothermal, jet_inputs, jet_performance, plotting, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Flight Envelope",
    "category": "Supersonic / Performance",
    "description": (
        "Level-flight Mach-altitude envelope from stall, thrust, dynamic-pressure, "
        "skin-temperature and Mach-ceiling limits, with the limiting factor at each altitude."
    ),
    "inputs": jet_inputs.MASS_INPUTS + [
        {"key": "q_max", "label": "Max Dynamic Pressure", "unit": "Pa", "type": "number",
         "default": "60000", "help": "Structural design limit."},
        {"key": "material", "label": "Skin Material", "type": "choice",
         "choices": list(aerothermal.MATERIALS) + ["No limit"],
         "default": "Carbon/epoxy, 120 C cure"},
        {"key": "use_ab", "label": "Use Afterburner", "type": "choice", "choices": ["Yes", "No"],
         "default": "Yes"},
    ] + jet_inputs.GEOMETRY_INPUTS + jet_inputs.ENGINE_INPUTS,
}


def run(inputs):
    try:
        config = jet_inputs.configuration(inputs)
        engine = jet_inputs.engine(inputs)
        mass = units.positive(inputs, "mass", "kg", "Mass", 105.0)
        cl_max = units.positive(inputs, "cl_max", "", "CLmax", 1.0)
        q_max = units.positive(inputs, "q_max", "Pa", "Max dynamic pressure", 60000.0)
        material = inputs.get("material") or "Carbon/epoxy, 120 C cure"
        limit = aerothermal.MATERIALS.get(material, float("inf"))
        use_ab = jet_inputs.yes(inputs, "use_ab") and engine.afterburner
        aircraft = jet_performance.JetAircraft(config, engine, cl_max=cl_max,
                                               max_dynamic_pressure=q_max, temperature_limit=limit)
        weight = mass * G

        rows, low, high, alts = [], [], [], []
        ceiling = None
        for h in [1000.0 * i for i in range(0, 21)]:
            env = aircraft.envelope_at(h, weight, use_ab)
            if env is None:
                ceiling = ceiling or h
                continue
            alts.append(h)
            low.append(env["min_mach"])
            high.append(env["max_mach"])
            rows.append([f"{h:,.0f}", f"{env['min_mach']:.2f}", env["low_limited_by"],
                         f"{env['max_mach']:.2f}", env["limited_by"],
                         "yes" if env["transonic_gap"] else ""])
        if not rows:
            raise ValueError("No level flight is possible at any altitude with this thrust.")
        r = report.Report("Flight Envelope")
        r.value("Weight", weight, "N", 1)
        r.value("Skin material limit", material if limit != float("inf") else "none")
        r.value("Afterburner", "on" if use_ab else "off")
        r.table(["Alt (m)", "Min M", "Set by", "Max M", "Set by", "Transonic gap"], rows)
        top = max(range(len(high)), key=lambda i: high[i])
        r.value("Highest Mach", high[top], "", 2)
        r.value("  at altitude", alts[top], "m", 0)
        r.value("Absolute ceiling (approx.)", ceiling if ceiling else alts[-1], "m", 0)
        if any(row[4] == "skin temperature" for row in rows):
            r.bullet("Skin temperature limits top speed: a higher-temperature resin or metal "
                     "leading edges would open the envelope.")
        if any(row[5] for row in rows):
            r.bullet("A transonic gap means level acceleration through Mach 1 is impossible "
                     "at that altitude.")

        figures = []
        if plotting.available():
            figures.append(plotting.line_chart("Flight Envelope", "Mach", "Altitude (m)",
                                               [("Minimum", low, alts), ("Maximum", high, alts)]))
        return report.result(r, outputs={
            "Max Mach": {"value": high[top], "unit": ""},
            "Altitude for Max Mach": {"value": alts[top], "unit": "m"}}, figures=figures)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
