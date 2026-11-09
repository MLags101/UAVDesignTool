"""
Specific Excess Power & Energy Climb

Maps Ps = V (T - D) / W over Mach and altitude, overlays Rutowski's
minimum-time climb path to the target condition, and checks the transonic
pinch: whether there is positive excess power all the way through Mach 1.
"""

from uavlib import jet_inputs, jet_performance, plotting, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Specific Excess Power & Energy Climb",
    "category": "Supersonic / Performance",
    "description": (
        "Ps contours on the Mach-altitude map, minimum-time and minimum-fuel climbs to a "
        "supersonic target by the energy method, and the transonic acceleration check."
    ),
    "inputs": jet_inputs.MASS_INPUTS + [
        {"key": "target_mach", "label": "Target Mach", "type": "number", "default": "1.6"},
        {"key": "target_altitude", "label": "Target Altitude", "unit": "m", "type": "number",
         "default": "11000"},
        {"key": "use_ab", "label": "Use Afterburner", "type": "choice", "choices": ["Yes", "No"],
         "default": "Yes"},
        {"key": "load_factor", "label": "Load Factor for Ps Map", "type": "number", "default": "1"},
    ] + jet_inputs.GEOMETRY_INPUTS + jet_inputs.ENGINE_INPUTS,
}


def run(inputs):
    try:
        config = jet_inputs.configuration(inputs)
        engine = jet_inputs.engine(inputs)
        mass = units.positive(inputs, "mass", "kg", "Mass", 105.0)
        cl_max = units.positive(inputs, "cl_max", "", "CLmax", 1.0)
        target_m = units.positive(inputs, "target_mach", "", "Target Mach", 1.6)
        target_h = units.optional(inputs, "target_altitude", "m", 11000.0)
        use_ab = jet_inputs.yes(inputs, "use_ab") and engine.afterburner
        n = units.positive(inputs, "load_factor", "", "Load factor", 1.0)
        aircraft = jet_performance.JetAircraft(config, engine, cl_max=cl_max)
        weight = mass * G

        machs = [0.2 + 0.05 * i for i in range(37)]
        altitudes = [500.0 * j for j in range(33)]
        grid = []
        for h in altitudes:
            row = []
            for m in machs:
                if m < aircraft.stall_mach(h, weight) * n ** 0.5:
                    row.append(None)
                    continue
                row.append(aircraft.excess_power(m, h, weight, n, use_ab))
            grid.append(row)

        r = report.Report("Specific Excess Power & Energy Climb")
        r.value("Weight", weight, "N", 1)
        r.value("Afterburner", "on" if use_ab else "off")
        r.section("Transonic Pinch (level flight, 1 g)")
        pinch_rows = []
        for h in (0.0, 5000.0, 9000.0, 11000.0, 13000.0):
            values = [aircraft.excess_power(m, h, weight, 1.0, use_ab) for m in (0.95, 1.0, 1.05, 1.1, 1.2)]
            pinch_rows.append([f"{h:,.0f}"] + [f"{v:.0f}" for v in values])
        r.table(["Alt (m)", "M0.95", "M1.0", "M1.05", "M1.1", "M1.2"], pinch_rows)
        target_ps = aircraft.excess_power(target_m, target_h, weight, 1.0, use_ab)
        r.value("Ps at target", target_ps, "m/s", 1)

        outputs = {"Ps at Target": {"value": target_ps, "unit": "m/s"}}
        paths = []
        try:
            fast = aircraft.energy_climb(weight, target_h, target_m, afterburner=use_ab)
            frugal = aircraft.energy_climb(weight, target_h, target_m, objective="fuel",
                                           afterburner=use_ab)
            r.section("Energy-Method Climb from Mach 0.3 at Sea Level")
            r.table(["Schedule", "Time (s)", "Fuel (kg)", "Distance (km)"],
                    [["Minimum time", f"{fast['time']:.0f}", f"{fast['fuel']:.2f}",
                      f"{fast['distance'] / 1000:.1f}"],
                     ["Minimum fuel", f"{frugal['time']:.0f}", f"{frugal['fuel']:.2f}",
                      f"{frugal['distance'] / 1000:.1f}"]])
            r.bullet("Rutowski paths are idealised: they assume instant zoom/dive along "
                     "constant energy height. Real schedules take somewhat longer.")
            outputs["Time to Target"] = {"value": fast["time"], "unit": "s"}
            outputs["Climb Fuel (min fuel)"] = {"value": frugal["fuel"], "unit": "kg"}
            paths = [("Min-time path", [p["mach"] for p in fast["path"]],
                      [p["altitude"] for p in fast["path"]]),
                     ("Min-fuel path", [p["mach"] for p in frugal["path"]],
                      [p["altitude"] for p in frugal["path"]])]
        except ValueError as exc:
            r.warn(f"Target not reachable: {exc}")

        gaps = [h for h in (0.0, 5000.0, 9000.0, 11000.0, 13000.0)
                if aircraft.envelope_at(h, weight, use_ab) and aircraft.envelope_at(h, weight, use_ab)["transonic_gap"]]
        if gaps:
            r.warn("Negative excess power around Mach 1 at " + ", ".join(f"{h:,.0f} m" for h in gaps)
                   + ": the aircraft must dive through the transonic drag rise there.")

        figures = []
        if plotting.available():
            figures.append(plotting.contour_chart(
                f"Specific Excess Power (m/s), n = {n:g}", "Mach", "Altitude (m)",
                machs, altitudes, grid, paths=paths))
        return report.result(r, outputs=outputs, figures=figures)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
