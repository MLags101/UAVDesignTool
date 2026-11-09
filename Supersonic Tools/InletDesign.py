"""
Supersonic Inlet Design

Chooses external-compression ramp angles for maximum total-pressure recovery
(Oswatitsch equal-strength shocks) and sizes the capture area for the engine
mass flow. Compares 0 (pitot), 1, 2 and 3 ramps against the MIL-E-5007D
reference recovery. Every 1% of recovery lost is roughly 1-1.5% of thrust.
"""

from uavlib import airbreathing, jet_inputs, plotting, report, units

TOOL_METADATA = {
    "name": "Supersonic Inlet Design",
    "category": "Supersonic / Propulsion",
    "description": (
        "Optimum ramp angles and pressure recovery for pitot and external-compression "
        "inlets, and the capture area needed for the engine at the design point."
    ),
    "inputs": [
        {"key": "mach", "label": "Design Mach", "type": "number", "default": "1.6"},
        {"key": "altitude", "label": "Design Altitude", "unit": "m", "type": "number",
         "default": "11000"},
        {"key": "ramps", "label": "Number of Ramps", "type": "choice",
         "choices": ["1", "2", "3", "0"], "default": "1"},
        {"key": "subsonic_recovery", "label": "Subsonic Diffuser Recovery", "type": "number",
         "default": "0.97"},
        {"key": "mass_flow", "label": "Engine Air Mass Flow", "unit": "kg/s", "type": "number",
         "help": "Leave blank to use the engine below at the design point."},
    ] + [spec for spec in jet_inputs.ENGINE_INPUTS if spec["key"] not in ("inlet",)],
}


def run(inputs):
    try:
        mach = units.positive(inputs, "mach", "", "Design Mach", 1.6)
        if not 1.0 < mach <= 2.0:
            raise ValueError("Inlet design Mach must be between 1 and 2.")
        altitude = units.optional(inputs, "altitude", "m", 11000.0)
        ramps = int(inputs.get("ramps") or 1)
        duct = units.optional(inputs, "subsonic_recovery", "", 0.97)

        design = airbreathing.optimum_ramps(mach, ramps)
        mil = airbreathing.mil_spec_recovery(mach)
        r = report.Report("Supersonic Inlet Design")
        r.value("Design Mach", mach, "", 3)
        r.value("Altitude", altitude, "m", 0)
        r.section(f"{ramps}-Ramp External Compression (Oswatitsch optimum)")
        rows = [[str(i + 1), f"{s['deflection_deg']:.2f}", f"{s['shock_angle_deg']:.2f}",
                 f"{s['mach_after']:.3f}", f"{s['recovery']:.4f}"]
                for i, s in enumerate(design["shocks"])]
        if rows:
            r.table(["Ramp", "Turn (deg)", "Shock (deg)", "Mach after", "Recovery"], rows)
        r.value("Mach at terminal shock", design["terminal_mach"], "", 3)
        r.value("Shock-system recovery", design["recovery"], "", 4)
        r.value("Total with subsonic diffuser", design["recovery"] * duct, "", 4)
        r.value("MIL-E-5007D reference", mil, "", 4)

        r.section("Comparison")
        comparison = [["Pitot (normal shock)", f"{airbreathing.pitot_recovery(mach):.4f}"]]
        for n in (1, 2, 3):
            comparison.append([f"{n} ramp(s)", f"{airbreathing.optimum_ramps(mach, n)['recovery']:.4f}"])
        r.table(["Inlet", "Shock recovery"], comparison)

        mass_flow = units.parse(inputs.get("mass_flow"), "", None)
        source = "given"
        if mass_flow is None:
            engine = jet_inputs.engine({**inputs, "inlet": "MIL-E-5007D"})
            mass_flow = engine.max_thrust(mach, altitude)["mass_flow"]
            source = "engine at design point"
        capture = airbreathing.capture_area(mass_flow, mach, altitude)
        r.section("Capture Area")
        r.value("Air mass flow", mass_flow, "kg/s", 3)
        r.value("  source", source)
        r.value("Capture area", capture, "m^2", 5)
        r.value("  equivalent diameter", (4 * capture / 3.14159265) ** 0.5, "m", 4)
        r.bullet("Ramps beyond two add little below Mach 2 but add length, weight and "
                 "bleed requirements; a pitot inlet is acceptable to about Mach 1.5.")
        if design["terminal_mach"] > 1.4:
            r.warn("Terminal shock above Mach 1.4 risks boundary-layer separation; add a ramp.")

        figures = []
        if plotting.available():
            machs = [1.0 + 0.05 * i for i in range(1, 21)]
            series = [("MIL-E-5007D", machs, [airbreathing.mil_spec_recovery(m) for m in machs]),
                      ("Pitot", machs, [airbreathing.pitot_recovery(m) for m in machs])]
            for n in (1, 2):
                series.append((f"{n} ramp", machs, [airbreathing.optimum_ramps(m, n)["recovery"]
                                                    for m in machs]))
            figures.append(plotting.line_chart("Inlet Pressure Recovery", "Mach",
                                               "Total-pressure recovery", series,
                                               markers=[("Design", mach, design["recovery"])]))
        return report.result(r, outputs={
            "Inlet Recovery": {"value": design["recovery"] * duct, "unit": ""},
            "Inlet Capture Area": {"value": capture, "unit": "m^2"}}, figures=figures)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
