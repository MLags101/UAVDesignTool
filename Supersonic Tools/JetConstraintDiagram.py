"""
Jet Constraint Diagram (thrust loading vs wing loading)

The supersonic equivalent of the propeller constraint diagram. Each
requirement becomes a curve of sea-level static thrust-to-weight against
wing loading through Mattingly's master equation, using the engine's own
thrust lapse at every flight condition and the configuration's Mach-dependent
drag polar. The design must lie above every curve and left of the landing line.
"""

from uavlib import jet_inputs, jet_performance, plotting, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Jet Constraint Diagram",
    "category": "Supersonic / Sizing",
    "description": (
        "T/W versus W/S for takeoff, landing, subsonic and supersonic cruise, "
        "maximum Mach, sustained turn and excess-power requirements, using the "
        "engine lapse and Mach-dependent drag."
    ),
    "inputs": [
        {"key": "mass", "label": "Takeoff Mass", "unit": "kg", "type": "number", "default": "105"},
        {"key": "cl_max", "label": "Max Lift Coefficient", "type": "number", "default": "1.0"},
        {"key": "takeoff_roll", "label": "Takeoff Ground Roll", "unit": "m", "type": "number",
         "default": "150", "help": "Blank for catapult or rocket-assisted launch."},
        {"key": "landing_speed", "label": "Max Approach Speed", "unit": "m/s", "type": "number",
         "default": "", "help": "Blank for parachute recovery."},
        {"key": "cruise_mach", "label": "Supersonic Cruise Mach", "type": "number", "default": "1.6"},
        {"key": "cruise_altitude", "label": "Cruise Altitude", "unit": "m", "type": "number",
         "default": "11000"},
        {"key": "cruise_ab", "label": "Afterburner in Cruise", "type": "choice",
         "choices": ["No (supercruise)", "Yes"], "default": "Yes"},
        {"key": "cruise_fraction", "label": "Weight Fraction at Cruise", "type": "number",
         "default": "0.85"},
        {"key": "max_mach", "label": "Maximum Mach (with afterburner)", "type": "number",
         "default": "2.0"},
        {"key": "max_mach_altitude", "label": "Maximum Mach Altitude", "unit": "m",
         "type": "number", "default": "13000"},
        {"key": "turn_g", "label": "Sustained Turn Load Factor", "type": "number", "default": "3",
         "help": "At the turn Mach and altitude below; blank to skip."},
        {"key": "turn_mach", "label": "Turn Mach", "type": "number", "default": "0.9"},
        {"key": "turn_altitude", "label": "Turn Altitude", "unit": "m", "type": "number",
         "default": "5000"},
        {"key": "ps", "label": "Transonic Excess Power", "unit": "m/s", "type": "number",
         "default": "20", "help": "Ps required at Mach 1.1 for a brisk transonic acceleration."},
        {"key": "ps_altitude", "label": "Excess Power Altitude", "unit": "m", "type": "number",
         "default": "9000"},
    ] + jet_inputs.GEOMETRY_INPUTS + jet_inputs.ENGINE_INPUTS,
}


def run(inputs):
    try:
        config = jet_inputs.configuration(inputs)
        engine = jet_inputs.engine(inputs)
        mass = units.positive(inputs, "mass", "kg", "Takeoff mass", 105.0)
        cl_max = units.positive(inputs, "cl_max", "", "CLmax", 1.0)
        roll = units.parse(inputs.get("takeoff_roll"), "m", None)
        landing = units.parse(inputs.get("landing_speed"), "m/s", None)
        cm = units.positive(inputs, "cruise_mach", "", "Cruise Mach", 1.6)
        ch = units.optional(inputs, "cruise_altitude", "m", 11000.0)
        cab = str(inputs.get("cruise_ab") or "Yes").startswith("Yes")
        cf = units.positive(inputs, "cruise_fraction", "", "Cruise weight fraction", 0.85)
        mm = units.positive(inputs, "max_mach", "", "Maximum Mach", 2.0)
        mh = units.optional(inputs, "max_mach_altitude", "m", 13000.0)
        turn_g = units.parse(inputs.get("turn_g"), "", None)
        tm = units.positive(inputs, "turn_mach", "", "Turn Mach", 0.9)
        th = units.optional(inputs, "turn_altitude", "m", 5000.0)
        ps = units.optional(inputs, "ps", "m/s", 20.0)
        psh = units.optional(inputs, "ps_altitude", "m", 9000.0)
        if engine.afterburner is False and cab:
            cab = False

        weight = mass * G
        ws_actual = weight / config.wing_area
        tw_actual = engine.sls_thrust / weight
        ws_grid = [ws_actual * (0.3 + 1.4 * i / 59) for i in range(60)]
        conditions = [
            (f"Cruise M{cm:g} {'wet' if cab else 'dry'}",
             dict(mach=cm, altitude=ch, weight_fraction=cf, afterburner=cab)),
            (f"Max Mach {mm:g}", dict(mach=mm, altitude=mh, weight_fraction=cf,
                                      afterburner=engine.afterburner)),
            (f"Ps {ps:g} m/s at M1.1", dict(mach=1.1, altitude=psh, excess_power=ps,
                                            weight_fraction=0.95, afterburner=engine.afterburner)),
        ]
        if turn_g:
            conditions.append((f"{turn_g:g} g turn M{tm:g}",
                               dict(mach=tm, altitude=th, load_factor=turn_g,
                                    weight_fraction=0.9, afterburner=engine.afterburner)))
        curves = []
        for label, cond in conditions:
            curves.append((label, ws_grid, [jet_performance.thrust_loading(ws, config, engine, **cond)
                                            for ws in ws_grid]))
        if roll:
            curves.append((f"Takeoff {roll:g} m", ws_grid,
                           [jet_performance.takeoff_thrust_loading(ws, engine, cl_max, roll)
                            for ws in ws_grid]))
        ws_landing = None
        if landing:
            ws_landing = jet_performance.landing_wing_loading(cl_max, landing, weight_fraction=0.75)

        def required_at(ws):
            values = []
            for label, cond in conditions:
                values.append((jet_performance.thrust_loading(ws, config, engine, **cond), label))
            if roll:
                values.append((jet_performance.takeoff_thrust_loading(ws, engine, cl_max, roll),
                               f"Takeoff {roll:g} m"))
            return max(values)

        need, driver = required_at(ws_actual)
        best = min(((required_at(ws)[0], ws) for ws in ws_grid
                    if ws_landing is None or ws <= ws_landing))

        r = report.Report("Jet Constraint Diagram")
        r.value("Takeoff mass", mass, "kg", 2)
        r.value("Current wing loading", ws_actual, "N/m^2", 1)
        r.value("Current SLS T/W (dry)", tw_actual, "", 3)
        r.section("At the Current Wing Loading")
        rows = []
        for label, cond in conditions:
            value = jet_performance.thrust_loading(ws_actual, config, engine, **cond)
            rows.append([label, f"{value:.3f}", "<-- drives" if label == driver else ""])
        if roll:
            value = jet_performance.takeoff_thrust_loading(ws_actual, engine, cl_max, roll)
            rows.append([f"Takeoff {roll:g} m", f"{value:.3f}",
                         "<-- drives" if driver.startswith("Takeoff") else ""])
        r.table(["Constraint", "T_SLS/W", ""], rows)
        r.value("Required T/W", need, "", 3)
        r.value("Required SLS thrust", need * weight, "N", 0)
        r.value("Thrust margin", tw_actual / need - 1, "", 3)
        if ws_landing:
            r.value("Max wing loading (landing)", ws_landing, "N/m^2", 1)
            if ws_actual > ws_landing:
                r.warn("Wing loading exceeds the landing limit: enlarge the wing or add lift devices.")
        r.section("Minimum-Thrust Design Point")
        r.value("Wing loading", best[1], "N/m^2", 1)
        r.value("Wing area", weight / best[1], "m^2", 3)
        r.value("T_SLS/W", best[0], "", 3)
        r.value("SLS thrust", best[0] * weight, "N", 0)
        r.note("Drag coefficients are held at the current configuration's values while W/S "
               "varies, the usual constraint-analysis assumption.")

        figures = []
        if plotting.available():
            fig = plotting.filled_region_chart(
                "Jet Constraint Diagram", "Wing loading W/S (N/m^2)", "T_SLS / W_TO", curves,
                design_point=("Current design", ws_actual, tw_actual), feasible="above")
            figures.append(fig)
        outputs = {"Required SLS Thrust": {"value": need * weight, "unit": "N"},
                   "Required T/W": {"value": need, "unit": ""},
                   "Optimum Wing Area": {"value": weight / best[1], "unit": "m^2"}}
        return report.result(r, outputs=outputs, figures=figures)
    except (units.UnitError, ValueError) as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
