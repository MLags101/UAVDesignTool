"""
Standard Atmosphere and Unit Converter

Air properties at altitude, density altitude from field conditions, and a
general unit converter. Density altitude is the practical output: a hot, humid
day at a modest elevation can fly like considerably higher ground, which is
what actually costs a heavily loaded model its takeoff or hover margin.
"""

from uavlib import atmosphere, report, units

TOOL_METADATA = {
    "name": "Atmosphere & Unit Converter",
    "category": "Shared / Reference",
    "description": (
        "Standard atmosphere properties at altitude, density altitude from "
        "measured temperature, pressure and humidity, and conversion between "
        "the metric and imperial units used on model specifications."
    ),
    "inputs": [
        {"key": "altitude", "label": "Altitude", "unit": "m", "type": "number",
         "default": "0", "help": "Accepts feet, e.g. '5000 ft'."},
        {"key": "temperature", "label": "Measured Temperature", "unit": "degC",
         "type": "number",
         "help": "Optional. With pressure, gives the real density altitude."},
        {"key": "pressure", "label": "Measured Pressure", "unit": "Pa",
         "type": "number",
         "help": "Optional. Station pressure, not sea-level corrected."},
        {"key": "humidity", "label": "Relative Humidity", "unit": "%",
         "type": "number", "default": "0"},
        {"key": "velocity", "label": "Airspeed", "unit": "m/s", "type": "number",
         "help": "Optional: gives dynamic pressure and Mach number."},
        {"key": "chord", "label": "Reference Length", "unit": "m",
         "type": "number", "help": "Optional: gives the Reynolds number."},
        {"key": "convert_value", "label": "Value to Convert", "type": "text",
         "help": "Optional, e.g. '10 in', '3.3 lb', '35 mph', '5 kg-cm'."},
    ],
}

# Conversions offered for each dimension the converter recognises.
CONVERSION_SETS = {
    "length": ["m", "cm", "mm", "in", "ft"],
    "mass": ["kg", "g", "lb", "oz"],
    "speed": ["m/s", "km/h", "mph", "kt", "ft/s"],
    "area": ["m^2", "cm^2", "in^2", "ft^2"],
    "force": ["N", "kgf", "gf", "lbf"],
    "torque": ["N.m", "kg-cm", "oz-in"],
    "power": ["W", "hp"],
    "energy": ["J", "Wh"],
    "charge": ["Ah", "mAh"],
    "angle": ["deg", "rad"],
    "time": ["s", "min", "h"],
}


def run(inputs):
    try:
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        temperature = units.parse(inputs.get("temperature"), "", None)
        pressure = units.parse(inputs.get("pressure"), "", None)
        humidity = units.fraction(inputs, "humidity", 0.0)
        velocity = units.optional(inputs, "velocity", "m/s", 0.0)
        chord = units.optional(inputs, "chord", "m", 0.0)
        convert_text = (inputs.get("convert_value") or "").strip()

        air = atmosphere.at(altitude)

        r = report.Report("Atmosphere")
        r.section(f"Standard Atmosphere at {altitude:,.0f} m")
        r.dual("Altitude", altitude, "m", "ft", 1)
        r.value("Temperature", air.temperature - 273.15, "degC", 2)
        r.value("  in kelvin", air.temperature, "K", 2)
        r.value("Pressure", air.pressure, "Pa", 1)
        r.value("  in hPa", air.pressure / 100.0, "hPa", 2)
        r.value("Density", air.density, "kg/m^3", 5)
        r.value("Density ratio (sigma)", air.density_ratio, "", 5)
        r.value("Dynamic viscosity", air.viscosity, "Pa.s", 9)
        r.value("Kinematic viscosity", air.kinematic_viscosity, "m^2/s", 9)
        r.dual("Speed of sound", air.sound_speed, "m/s", "mph", 2)

        if temperature is not None or pressure is not None:
            station_pressure = pressure if pressure is not None else air.pressure
            station_temp = (temperature if temperature is not None
                            else air.temperature - 273.15)
            measured_density = atmosphere.density_from_conditions(
                station_pressure, station_temp, humidity)
            density_alt = atmosphere.density_altitude(measured_density)

            r.section("Measured Conditions")
            r.value("Temperature", station_temp, "degC", 2)
            r.value("Pressure", station_pressure, "Pa", 1)
            r.value("Relative humidity", humidity * 100, "%", 0)
            r.value("Actual density", measured_density, "kg/m^3", 5)
            r.value("Density vs standard",
                    100 * (measured_density / air.density - 1), "%", 2)
            r.blank()
            r.dual("DENSITY ALTITUDE", density_alt, "m", "ft", 1)
            r.value("Difference from field elevation", density_alt - altitude,
                    "m", 1)

            if density_alt > altitude + 300:
                r.warn(f"The air behaves like {density_alt:,.0f} m rather than "
                       f"{altitude:,.0f} m. Expect longer takeoff runs, reduced "
                       "climb and less hover margin.")
                penalty = air.density / measured_density
                r.value("Takeoff distance factor", penalty, "x", 3)
                r.value("Thrust reduction", 100 * (1 - measured_density
                                                   / atmosphere.RHO_0), "%", 1)
            if humidity > 0.5:
                r.bullet("Humid air is less dense than dry air at the same "
                         "pressure, so high humidity hurts performance rather "
                         "than helping it.")

        if velocity > 0:
            r.section("Flow at " + f"{velocity:g} m/s")
            r.value("Dynamic pressure", 0.5 * air.density * velocity ** 2, "Pa", 2)
            r.value("Mach number", velocity / air.sound_speed, "", 4)
            r.dual("Airspeed", velocity, "m/s", "mph", 2)
            r.value("  also", units.ms_to_kmh(velocity), "km/h", 2)
            r.value("  also", units.ms_to_kt(velocity), "knots", 2)
            if chord > 0:
                re = atmosphere.reynolds(velocity, chord, altitude)
                r.value("Reynolds number", re, "", 0)
                r.blank()
                r.text(f"  {atmosphere.reynolds_note(re)}")

        if convert_text:
            r.section("Unit Conversion")
            r.value("Input", convert_text)
            converted = False
            for dimension, targets in CONVERSION_SETS.items():
                base = units._BASE.get(dimension, "")
                try:
                    value = units.parse(convert_text, base, None)
                except units.UnitError:
                    continue
                if value is None:
                    continue
                # Only report the dimension whose unit the input actually named.
                suffix = convert_text.lower().strip()
                for character in "0123456789.+-eE ":
                    suffix = suffix.replace(character, "")
                if not suffix:
                    continue
                if units._DIMENSION_OF.get(
                        suffix.replace("·", ".").replace(" ", "")) != dimension:
                    continue
                rows = []
                for target in targets:
                    try:
                        rows.append([target, f"{units.to(value, target):,.6g}"])
                    except units.UnitError:
                        continue
                if rows:
                    r.blank()
                    r.value("Dimension", dimension)
                    r.table(["Unit", "Value"], rows)
                    converted = True
                    break
            if not converted:
                r.warn("Could not identify the unit. Try a form like "
                       "'10 in', '3.3 lb', '35 mph' or '5 kg-cm'.")

        r.section("Altitude Reference")
        rows = []
        for h in (0, 500, 1000, 2000, 3000, 5000):
            sample = atmosphere.at(h)
            rows.append([f"{h:,}", f"{sample.temperature - 273.15:.1f}",
                         f"{sample.density:.4f}", f"{sample.density_ratio:.3f}",
                         f"{sample.sound_speed:.1f}"])
        r.table(["Alt m", "T degC", "rho", "sigma", "a m/s"], rows)
        r.text("  Thrust and lift both scale with sigma, so a model that just")
        r.text("  flies at sea level may not at a mountain field.")

        return report.result(r, outputs={
            "Air Density": {"value": air.density, "unit": "kg/m^3"},
            "Air Temperature": {"value": air.temperature - 273.15, "unit": "degC"},
            "Speed of Sound": {"value": air.sound_speed, "unit": "m/s"},
        })

    except units.UnitError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
