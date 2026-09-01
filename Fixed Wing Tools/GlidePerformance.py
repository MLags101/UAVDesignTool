"""
Glide Performance and Sink Rate

Best glide, minimum sink and how far the model reaches with the motor stopped.
Two distinct speeds matter and they are often confused: best glide (minimum
drag) covers the most ground, minimum sink stays airborne longest. Minimum sink
is about 24% slower than best glide.

The dead-stick range figure is the practical one -- it decides whether a field
is reachable when the motor quits.
"""

import math

from uavlib import aero, atmosphere, plotting, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Glide Performance",
    "category": "Fixed Wing / Performance",
    "description": (
        "Glide ratio, best glide and minimum sink speeds, sink rate and "
        "dead-stick range from altitude. Includes the effect of wind and of "
        "ballasting for penetration."
    ),
    "inputs": [
        {"key": "mass", "label": "Total Mass", "unit": "kg", "type": "number"},
        {"key": "wing_area", "label": "Wing Area (S)", "unit": "m^2",
         "type": "number"},
        {"key": "span", "label": "Wing Span (b)", "unit": "m", "type": "number"},
        {"key": "cd0", "label": "Parasite Drag (CD0)", "type": "number",
         "default": "0.030",
         "help": "With the motor stopped; a windmilling propeller adds "
                 "roughly 0.01-0.02."},
        {"key": "cl_max", "label": "Max Lift Coefficient", "type": "number",
         "default": "1.2"},
        {"key": "altitude", "label": "Starting Altitude", "unit": "m",
         "type": "number", "default": "100"},
        {"key": "headwind", "label": "Headwind", "unit": "m/s", "type": "number",
         "default": "0", "help": "Negative for a tailwind."},
        {"key": "sink_air", "label": "Air Mass Sink Rate", "unit": "m/s",
         "type": "number", "default": "0",
         "help": "Positive if the air itself is sinking. Use a negative value "
                 "for lift in a thermal."},
        {"key": "ballast", "label": "Added Ballast", "unit": "kg",
         "type": "number", "default": "0",
         "help": "Ballast raises the speeds but leaves the glide ratio "
                 "unchanged, which is why gliders carry it in wind."},
    ],
}


def run(inputs):
    try:
        mass = units.positive(inputs, "mass", "kg", "Mass")
        wing_area = units.positive(inputs, "wing_area", "m^2", "Wing area")
        span = units.positive(inputs, "span", "m", "Span")
        cd0 = units.positive(inputs, "cd0", "", "CD0", default=0.030)
        cl_max = units.positive(inputs, "cl_max", "", "CLmax", default=1.2)
        altitude = units.optional(inputs, "altitude", "m", 100.0)
        headwind = units.optional(inputs, "headwind", "m/s", 0.0)
        sink_air = units.optional(inputs, "sink_air", "m/s", 0.0)
        ballast = units.optional(inputs, "ballast", "kg", 0.0)

        total_mass = mass + max(0.0, ballast)
        aspect_ratio = span ** 2 / wing_area
        oswald = aero.oswald_efficiency(aspect_ratio)
        k = aero.induced_drag_factor(aspect_ratio, oswald)

        best_ld, cl_best = aero.ld_max(cd0, k)
        v_best_glide = aero.stall_speed_at_cl(total_mass, wing_area, cl_best)
        cl_min_sink = math.sqrt(3.0 * cd0 / k)
        v_min_sink = aero.stall_speed_at_cl(total_mass, wing_area, cl_min_sink)
        v_stall = aero.stall_speed(total_mass, wing_area, cl_max)

        # L/D at minimum sink is 0.866 of the best value.
        ld_min_sink = best_ld * (2.0 * math.sqrt(3.0) / 4.0)
        sink_best_glide = v_best_glide / best_ld
        sink_minimum = v_min_sink / ld_min_sink

        r = report.Report("Glide Performance")
        r.section("Configuration")
        r.dual("Mass", total_mass, "kg", "lb", 3)
        if ballast > 0:
            r.value("  of which ballast", ballast, "kg", 3)
        r.value("Wing loading", total_mass * G / wing_area, "N/m^2", 1)
        r.value("Aspect ratio", aspect_ratio, "", 2)
        r.value("CD0", cd0, "", 5)
        r.value("Oswald efficiency", oswald, "", 3)
        r.note(aero.oswald_note(aspect_ratio))

        r.section("Best Glide (maximum distance)")
        r.value("Glide ratio (L/D max)", best_ld, ":1", 2)
        r.value("  at CL", cl_best, "", 3)
        r.dual("Speed", v_best_glide, "m/s", "mph", 2)
        r.value("Sink rate", sink_best_glide, "m/s", 3)
        r.value("Glide angle", math.degrees(math.atan(1.0 / best_ld)), "deg", 2)

        r.section("Minimum Sink (maximum time)")
        r.value("L/D", ld_min_sink, ":1", 2)
        r.value("  at CL", cl_min_sink, "", 3)
        r.dual("Speed", v_min_sink, "m/s", "mph", 2)
        r.value("Sink rate", sink_minimum, "m/s", 3)
        r.value("Speed ratio to best glide", v_min_sink / v_best_glide, "", 3)
        r.dual("Stall speed", v_stall, "m/s", "mph", 2)

        if v_min_sink < v_stall:
            r.warn("The minimum-sink speed is below the stall. This wing "
                   "cannot reach its theoretical best; use 1.1 Vs instead.")

        r.section(f"Dead-Stick from {altitude:g} m")
        still_range = altitude * best_ld
        r.value("Range in still air", still_range, "m", 0)
        r.value("  in km", still_range / 1000.0, "km", 3)
        r.value("Time at best glide", altitude / sink_best_glide, "s", 1)
        r.value("Time at minimum sink", altitude / sink_minimum, "s", 1)

        if headwind != 0 or sink_air != 0:
            effective_sink = sink_best_glide + sink_air
            if effective_sink <= 0:
                r.blank()
                r.bullet("The air is rising faster than the model sinks: it "
                         "will climb rather than descend.")
            else:
                ground_speed = v_best_glide - headwind
                effective_ld = ground_speed / effective_sink
                r.blank()
                r.dual("Headwind", headwind, "m/s", "mph", 2)
                r.value("Air mass sink", sink_air, "m/s", 2)
                r.value("Effective glide ratio", effective_ld, ":1", 2)
                r.value("Range over the ground", altitude * effective_ld, "m", 0)
                if effective_ld < best_ld:
                    r.value("Range lost", still_range - altitude * effective_ld,
                            "m", 0)
                if headwind > 0:
                    # Speed to fly into wind: push forward of best glide.
                    speed_to_fly = math.sqrt(v_best_glide ** 2
                                             + headwind * v_best_glide)
                    r.dual("Speed to fly into wind", speed_to_fly, "m/s", "mph", 2)
                    r.text("  Into a headwind, fly faster than best glide;")
                    r.text("  downwind or in lift, fly slower.")

        if ballast > 0:
            r.section("Ballast Effect")
            base_v = aero.stall_speed_at_cl(mass, wing_area, cl_best)
            r.value("Glide ratio unchanged", best_ld, ":1", 2)
            r.dual("Speed without ballast", base_v, "m/s", "mph", 2)
            r.dual("Speed with ballast", v_best_glide, "m/s", "mph", 2)
            r.value("Speed increase", 100 * (v_best_glide / base_v - 1), "%", 1)
            r.value("Sink rate increase",
                    100 * (v_best_glide / base_v - 1), "%", 1)
            r.text("  Ballast leaves the glide ratio alone but raises every")
            r.text("  speed, which is exactly what is wanted for penetrating")
            r.text("  wind -- at the cost of a higher sink rate in still air.")

        r.section("Assessment")
        if best_ld > 25:
            r.bullet("Sailplane-class performance.")
        elif best_ld > 15:
            r.bullet("Good glide performance, typical of a clean thermal model.")
        elif best_ld > 9:
            r.bullet("Respectable for a powered sport model.")
        else:
            r.bullet("Poor glide. Check CD0 and aspect ratio; a windmilling "
                     "propeller alone can cost several points of L/D.")
        r.bullet(f"From {altitude:g} m, a {best_ld:.0f}:1 glide reaches "
                 f"{still_range / 1000:.2f} km in still air. Plan dead-stick "
                 "landings on roughly half that, to leave a circuit.")

        figures = []
        if plotting.available():
            try:
                speeds, sinks, ratios = [], [], []
                v_low = max(v_stall, v_min_sink * 0.6)
                for i in range(80):
                    v = v_low + (v_best_glide * 2.2 - v_low) * i / 79
                    cl = aero.cl_required(total_mass, wing_area, v)
                    if cl > cl_max:
                        continue
                    cd = aero.drag_polar(cl, cd0, k)
                    sink = v * cd / cl
                    speeds.append(v)
                    sinks.append(-sink)
                    ratios.append(cl / cd)
                figures.append(plotting.line_chart(
                    "Glide Polar", "Airspeed (m/s)", "Vertical speed (m/s)",
                    [("Sink rate", speeds, sinks)],
                    markers=[(f"Min sink {sink_minimum:.2f} m/s",
                              v_min_sink, -sink_minimum),
                             (f"Best glide {best_ld:.1f}:1",
                              v_best_glide, -sink_best_glide)]))
                figures.append(plotting.line_chart(
                    "Glide Ratio vs Speed", "Airspeed (m/s)", "L/D",
                    [("L/D", speeds, ratios)],
                    markers=[(f"Best {best_ld:.1f}", v_best_glide, best_ld)]))
            except Exception:
                r.note("Charts could not be generated.")

        return report.result(r, outputs={
            "Glide Ratio": {"value": best_ld},
            "Best Glide Speed": {"value": v_best_glide, "unit": "m/s"},
            "Minimum Sink Rate": {"value": sink_minimum, "unit": "m/s"},
            "Minimum Sink Speed": {"value": v_min_sink, "unit": "m/s"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
