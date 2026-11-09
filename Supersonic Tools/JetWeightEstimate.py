"""
Jet UAV Weight Estimate

Closes the takeoff mass of a small jet UAV with a physical build-up: wing and
tail skins by areal mass, the wing spar sized for bending and stiffness at the
design load factor, fuselage shell, engine from its thrust-to-weight ratio,
installation, fuel system, fixed equipment and recovery. Checks that the fuel
fits in the wing and fuselage.
"""

from uavlib import jet_inputs, jet_weights, plotting, report, units

TOOL_METADATA = {
    "name": "Jet UAV Weight Estimate",
    "category": "Supersonic / Sizing",
    "description": (
        "Takeoff mass closure and component breakdown for a small jet UAV, with spar sizing "
        "and an internal fuel volume check."
    ),
    "inputs": [
        {"key": "payload", "label": "Payload", "unit": "kg", "type": "number", "default": "10"},
        {"key": "fuel", "label": "Fuel Capacity", "unit": "kg", "type": "number", "default": "40"},
        {"key": "load_factor", "label": "Ultimate Load Factor", "type": "number", "default": "9",
         "help": "Limit load times 1.5."},
        {"key": "skin_areal_mass", "label": "Wing/Tail Skin Areal Mass", "unit": "kg/m^2",
         "type": "number", "default": "2.2"},
        {"key": "body_areal_mass", "label": "Fuselage Areal Mass", "unit": "kg/m^2",
         "type": "number", "default": "3.5"},
        {"key": "engine_tw", "label": "Engine Thrust/Weight", "type": "number", "default": "10"},
        {"key": "fixed_mass", "label": "Avionics & Fixed Equipment", "unit": "kg", "type": "number",
         "default": "4"},
        {"key": "recovery_fraction", "label": "Recovery System Fraction", "type": "number",
         "default": "0.05", "help": "Parachute/airbag or landing gear, of takeoff mass."},
    ] + jet_inputs.GEOMETRY_INPUTS + [s for s in jet_inputs.ENGINE_INPUTS
                                       if s["key"] in ("sls_thrust", "afterburner")],
}


def run(inputs):
    try:
        config = jet_inputs.configuration(inputs)
        payload = units.optional(inputs, "payload", "kg", 10.0)
        fuel = units.optional(inputs, "fuel", "kg", 40.0)
        tech = jet_weights.Technology(
            skin_areal_mass=units.positive(inputs, "skin_areal_mass", "", "Skin areal mass", 2.2),
            body_areal_mass=units.positive(inputs, "body_areal_mass", "", "Body areal mass", 3.5),
            engine_thrust_to_weight=units.positive(inputs, "engine_tw", "", "Engine T/W", 10.0),
            fixed_mass=units.optional(inputs, "fixed_mass", "kg", 4.0),
            recovery_fraction=units.optional(inputs, "recovery_fraction", "", 0.05))
        thrust = units.positive(inputs, "sls_thrust", "N", "SLS thrust", 1500.0)
        afterburner = jet_inputs.yes(inputs, "afterburner")
        n = units.positive(inputs, "load_factor", "", "Load factor", 9.0)

        mass, breakdown, notes = jet_weights.close(config, tech, thrust, afterburner, payload, fuel, n)
        volume = jet_weights.fuel_volume_available(config, tech)
        capacity = volume * tech.fuel_density

        r = report.Report("Jet UAV Weight Estimate")
        r.value("Takeoff mass", mass, "kg", 2)
        r.value("Empty mass", mass - payload - fuel, "kg", 2)
        r.value("Empty mass fraction", (mass - payload - fuel) / mass, "", 3)
        r.value("Fuel fraction", fuel / mass, "", 3)
        r.value("SLS T/W (dry)", thrust / (mass * 9.80665), "", 3)
        r.value("Wing loading", mass * 9.80665 / config.wing_area, "N/m^2", 1)
        r.section("Breakdown")
        r.table(["Item", "kg", "%"], [[k, f"{v:.2f}", f"{100 * v / mass:.1f}"]
                                      for k, v in breakdown.items()])
        r.section("Wing Spar")
        r.value("Spar cap area (each, root)", notes["spar_cap_area"] * 1e6, "mm^2", 1)
        r.value("Sized by", notes["spar_limited_by"])
        r.section("Fuel Volume")
        r.value("Wing internal volume", jet_weights.wing_volume(config) * 1000, "L", 1)
        r.value("Fuselage internal volume", jet_weights.body_volume(config) * 1000, "L", 1)
        r.value("Usable fuel capacity", capacity, "kg", 1)
        r.value("Fuel volume margin", capacity / fuel - 1 if fuel else 0.0, "", 3)
        if fuel > capacity:
            r.warn("The fuel does not fit: thin supersonic wings hold little, so lengthen the "
                   "fuselage or accept less fuel.")
        r.note("Areal masses are technology assumptions; calibrate them against a built part.")

        figures = []
        if plotting.available():
            figures.append(plotting.bar_chart("Mass Breakdown", "Mass (kg)", "",
                                              list(breakdown), list(breakdown.values())))
        return report.result(r, outputs={
            "Takeoff Mass": {"value": mass, "unit": "kg"},
            "Empty Mass": {"value": mass - payload - fuel, "unit": "kg"},
            "Fuel Capacity Available": {"value": capacity, "unit": "kg"}}, figures=figures)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
