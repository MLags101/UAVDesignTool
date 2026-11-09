"""
Jet Engine Cycle

Off-design performance of a single-spool turbojet, with or without an
afterburner: thrust, fuel flow and TSFC across Mach and altitude, scaled to
the sea-level static thrust you specify (Mattingly, Elements of Propulsion).
Use it to see how much thrust is left at the supersonic design point and what
the afterburner buys.
"""

from uavlib import jet_inputs, plotting, report, units

TOOL_METADATA = {
    "name": "Jet Engine Cycle",
    "category": "Supersonic / Propulsion",
    "description": (
        "Turbojet / afterburning turbojet thrust, fuel flow and TSFC versus Mach and "
        "altitude from a parametric cycle, with thrust lapse curves."
    ),
    "inputs": jet_inputs.ENGINE_INPUTS + [
        {"key": "mach", "label": "Operating Mach", "type": "number", "default": "1.6"},
        {"key": "altitude", "label": "Operating Altitude", "unit": "m", "type": "number",
         "default": "11000"},
    ],
}


def run(inputs):
    try:
        engine = jet_inputs.engine(inputs)
        mach = units.optional(inputs, "mach", "", 1.6)
        altitude = units.optional(inputs, "altitude", "m", 11000.0)
        sls = engine.point(0.0, 0.0)
        dry = engine.max_thrust(mach, altitude, False)

        r = report.Report("Jet Engine Cycle")
        r.section("Sea-Level Static (dry)")
        r.dual("Thrust", sls["thrust"], "N", "lbf", 1)
        r.value("Air mass flow", sls["mass_flow"], "kg/s", 3)
        r.value("Specific thrust", sls["specific_thrust"], "N.s/kg", 1)
        r.value("TSFC", sls["tsfc"] * 1e6, "mg/(N.s)", 2)
        r.value("  also", sls["tsfc"] * 3600 * 9.80665, "1/h", 3)
        r.value("Fuel flow", sls["fuel_flow"] * 60, "kg/min", 3)
        r.section(f"Mach {mach:g} at {altitude:,.0f} m")
        r.value("Compressor pressure ratio", dry["pi_c"], "", 3)
        r.value("Turbine inlet temperature", dry["tt4"], "K", 0)
        r.value("Inlet recovery", dry["inlet_recovery"], "", 4)
        r.value("Dry thrust", dry["thrust"], "N", 1)
        r.value("Dry TSFC", dry["tsfc"] * 1e6, "mg/(N.s)", 2)
        r.value("Dry lapse (T / T_SLS)", dry["thrust"] / engine.sls_thrust, "", 3)
        outputs = {"Dry Thrust at Design Point": {"value": dry["thrust"], "unit": "N"},
                   "Dry TSFC at Design Point": {"value": dry["tsfc"], "unit": "kg/(N.s)"},
                   "SLS Mass Flow": {"value": sls["mass_flow"], "unit": "kg/s"}}
        if engine.afterburner:
            wet = engine.max_thrust(mach, altitude, True)
            r.value("Afterburning thrust", wet["thrust"], "N", 1)
            r.value("Afterburning TSFC", wet["tsfc"] * 1e6, "mg/(N.s)", 2)
            r.value("Afterburner thrust gain", wet["thrust"] / dry["thrust"], "x", 2)
            outputs["Wet Thrust at Design Point"] = {"value": wet["thrust"], "unit": "N"}

        machs = [0.0, 0.4, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0]
        altitudes = [0.0, 5000.0, 11000.0, 15000.0]
        rows = []
        for h in altitudes:
            for m in machs:
                d = engine.max_thrust(m, h, False)
                row = [f"{h:,.0f}", f"{m:.1f}", f"{d['thrust']:.0f}", f"{d['tsfc'] * 1e6:.1f}"]
                if engine.afterburner:
                    w = engine.max_thrust(m, h, True)
                    row += [f"{w['thrust']:.0f}", f"{w['tsfc'] * 1e6:.1f}"]
                rows.append(row)
        headers = ["Alt (m)", "Mach", "Dry T (N)", "Dry TSFC"]
        if engine.afterburner:
            headers += ["Wet T (N)", "Wet TSFC"]
        r.section("Performance Map (TSFC in mg/(N.s))")
        r.table(headers, rows)
        r.bullet("Ram compression raises thrust with Mach while the compressor unloads; "
                 "altitude cuts thrust roughly with density.")

        figures = []
        if plotting.available():
            series = [(f"{h / 1000:g} km dry", machs, [engine.lapse(m, h, False) for m in machs])
                      for h in altitudes]
            if engine.afterburner:
                series.append(("11 km wet", machs, [engine.lapse(m, 11000.0, True) for m in machs]))
            figures.append(plotting.line_chart("Thrust Lapse", "Mach", "Thrust / SLS dry thrust",
                                               series))
        return report.result(r, outputs=outputs, figures=figures)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
