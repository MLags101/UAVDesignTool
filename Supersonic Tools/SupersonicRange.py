"""
Supersonic Range & Cruise

Specific range (distance per kg of fuel) versus Mach at several altitudes, the
best subsonic and supersonic cruise conditions, and the range on a given fuel
load by stepwise Breguet integration with part-power fuel flow from the
engine cycle. Shows the price of going supersonic.
"""

from uavlib import jet_inputs, jet_performance, plotting, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Supersonic Range & Cruise",
    "category": "Supersonic / Performance",
    "description": (
        "Specific range versus Mach and altitude, best cruise conditions, and range "
        "at a chosen Mach on a given cruise fuel load."
    ),
    "inputs": jet_inputs.MASS_INPUTS + [
        {"key": "cruise_fuel", "label": "Fuel Available for Cruise", "unit": "kg",
         "type": "number", "default": "20"},
        {"key": "cruise_mach", "label": "Cruise Mach", "type": "number", "default": "1.6"},
        {"key": "cruise_altitude", "label": "Cruise Altitude", "unit": "m", "type": "number",
         "default": "11000"},
        {"key": "allow_ab", "label": "Allow Afterburner in Cruise", "type": "choice",
         "choices": ["Yes", "No"], "default": "Yes"},
    ] + jet_inputs.GEOMETRY_INPUTS + jet_inputs.ENGINE_INPUTS,
}


def run(inputs):
    try:
        config = jet_inputs.configuration(inputs)
        engine = jet_inputs.engine(inputs)
        mass = units.positive(inputs, "mass", "kg", "Mass", 105.0)
        cl_max = units.positive(inputs, "cl_max", "", "CLmax", 1.0)
        fuel = units.positive(inputs, "cruise_fuel", "kg", "Cruise fuel", 20.0)
        mach = units.positive(inputs, "cruise_mach", "", "Cruise Mach", 1.6)
        altitude = units.optional(inputs, "cruise_altitude", "m", 11000.0)
        allow = jet_inputs.yes(inputs, "allow_ab") and engine.afterburner
        if fuel >= mass:
            raise ValueError("Cruise fuel must be less than the aircraft mass.")
        aircraft = jet_performance.JetAircraft(config, engine, cl_max=cl_max, afterburner_allowed=allow)
        weight = mass * G

        machs = [0.5 + 0.05 * i for i in range(31)]
        altitudes = [3000.0, 7000.0, 11000.0, 14000.0]
        series, best_sub, best_sup = [], (0, None, None), (0, None, None)
        for h in altitudes:
            xs, ys = [], []
            for m in machs:
                if m < aircraft.stall_mach(h, weight) * 1.2:
                    continue
                sr = aircraft.specific_range(m, h, weight, allow)
                if sr is None:
                    continue
                xs.append(m)
                ys.append(sr / 1000.0)
                if m < 1 and sr > best_sub[0]:
                    best_sub = (sr, m, h)
                if m >= 1.2 and sr > best_sup[0]:
                    best_sup = (sr, m, h)
            if xs:
                series.append((f"{h / 1000:g} km", xs, ys))

        r = report.Report("Supersonic Range & Cruise")
        r.value("Mass at cruise start", mass, "kg", 2)
        r.value("Cruise fuel", fuel, "kg", 2)
        r.section("Best Cruise Conditions (on the grid)")
        if best_sub[1]:
            r.value("Subsonic", f"Mach {best_sub[1]:.2f} at {best_sub[2]:,.0f} m, "
                                f"{best_sub[0] / 1000:.2f} km/kg")
        if best_sup[1]:
            r.value("Supersonic", f"Mach {best_sup[1]:.2f} at {best_sup[2]:,.0f} m, "
                                  f"{best_sup[0] / 1000:.2f} km/kg")
        if best_sub[1] and best_sup[1]:
            r.bullet(f"Supersonic cruise costs {best_sub[0] / best_sup[0]:.1f}x the fuel per km "
                     "of the best subsonic cruise.")

        outputs = {}
        r.section(f"Cruise at Mach {mach:g}, {altitude:,.0f} m")
        try:
            leg = aircraft.cruise(mach, altitude, weight, fuel, afterburner=allow)
            flow, drag, cl = aircraft.cruise_fuel_flow(mach, altitude, weight, allow)
            r.value("Range", leg["range"] / 1000, "km", 1)
            r.value("Time", leg["time"] / 60, "min", 1)
            r.value("Initial CL", cl, "", 3)
            r.value("Initial drag", drag, "N", 1)
            r.value("Initial fuel flow", flow * 60, "kg/min", 3)
            r.value("Initial L/D", weight / drag, "", 2)
            cl_best = (config.cd0(mach, altitude)["total"] / config.k_factor(mach)) ** 0.5
            r.value("CL for best L/D", cl_best, "", 3)
            if cl < 0.5 * cl_best:
                r.warn(f"Flying at CL {cl:.3f}, far below the best-L/D CL of {cl_best:.2f}: the "
                       "wing is lightly loaded for this dynamic pressure. Cruise higher or raise "
                       "the wing loading (smaller wing) to cut drag.")
            needs_ab = drag > engine.max_thrust(mach, altitude, False)["thrust"]
            r.value("Afterburner needed", "yes" if needs_ab else "no (supercruise)")
            outputs = {"Cruise Range": {"value": leg["range"], "unit": "m"},
                       "Cruise Time": {"value": leg["time"], "unit": "s"}}
        except ValueError as exc:
            r.warn(str(exc))

        figures = []
        if plotting.available() and series:
            figures.append(plotting.line_chart("Specific Range", "Mach", "km per kg of fuel",
                                               series))
        return report.result(r, outputs=outputs, figures=figures)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
