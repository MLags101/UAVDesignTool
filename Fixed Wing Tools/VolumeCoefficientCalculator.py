"""
Tail Volume Coefficient Sizing (Horizontal and Vertical)

An earlier version advertised the vertical tail coefficient but could only size
the horizontal one, because it always divided by the wing chord. The two
coefficients use different reference lengths:

    Vh = (Sh * Lh) / (Sw * MAC)     horizontal, referenced to the chord
    Vv = (Sv * Lv) / (Sw * b)       vertical, referenced to the SPAN

Using the chord for the vertical tail overestimates the required area several
times over, since span is much larger than chord.
"""

from uavlib import report, units

TOOL_METADATA = {
    "name": "Tail Volume Coefficient Sizing",
    "category": "Fixed Wing / Sizing",
    "description": (
        "Sizes horizontal and vertical stabilisers from target volume "
        "coefficients, or reports the coefficients of an existing tail. The "
        "vertical tail is referenced to wing SPAN, the horizontal to wing MAC."
    ),
    "inputs": [
        {"key": "mode", "label": "Mode", "type": "choice",
         "choices": ["Size tail from target coefficient",
                     "Check coefficients of existing tail"],
         "default": "Size tail from target coefficient"},
        {"key": "aircraft_type", "label": "Aircraft Type", "type": "choice",
         "choices": ["Trainer", "Sport", "Aerobatic", "Glider", "FPV / camera",
                     "Flying wing"],
         "default": "Sport",
         "help": "Sets the suggested coefficient range."},
        {"key": "wing_area", "label": "Wing Area (Sw)", "unit": "m^2", "type": "number"},
        {"key": "span", "label": "Wing Span (b)", "unit": "m", "type": "number"},
        {"key": "mac", "label": "Wing MAC", "unit": "m", "type": "number"},
        {"key": "l_h", "label": "Horizontal Tail Arm (Lh)", "unit": "m", "type": "number"},
        {"key": "l_v", "label": "Vertical Tail Arm (Lv)", "unit": "m", "type": "number",
         "help": "Usually within a few percent of the horizontal arm."},
        {"key": "vh_target", "label": "Target Vh", "type": "number",
         "help": "Blank uses the value suggested for the aircraft type."},
        {"key": "vv_target", "label": "Target Vv", "type": "number",
         "help": "Blank uses the value suggested for the aircraft type."},
        {"key": "s_h", "label": "Existing Horizontal Area", "unit": "m^2",
         "type": "number", "help": "Check mode only."},
        {"key": "s_v", "label": "Existing Vertical Area", "unit": "m^2",
         "type": "number", "help": "Check mode only."},
    ],
}

# Typical volume coefficients by model class. Vh is referenced to the MAC and
# Vv to the span, which is why Vv is an order of magnitude smaller.
TYPICAL = {
    "Trainer":      {"vh": (0.50, 0.70), "vv": (0.040, 0.055)},
    "Sport":        {"vh": (0.40, 0.60), "vv": (0.030, 0.045)},
    "Aerobatic":    {"vh": (0.35, 0.50), "vv": (0.035, 0.050)},
    "Glider":       {"vh": (0.40, 0.60), "vv": (0.020, 0.035)},
    "FPV / camera": {"vh": (0.50, 0.70), "vv": (0.035, 0.050)},
    "Flying wing":  {"vh": (0.00, 0.05), "vv": (0.000, 0.020)},
}


def run(inputs):
    try:
        mode = inputs.get("mode") or "Size tail from target coefficient"
        aircraft = inputs.get("aircraft_type") or "Sport"
        wing_area = units.positive(inputs, "wing_area", "m^2", "Wing area")
        span = units.positive(inputs, "span", "m", "Wing span")
        mac = units.positive(inputs, "mac", "m", "Wing MAC")
        l_h = units.optional(inputs, "l_h", "m", 0.0)
        l_v = units.optional(inputs, "l_v", "m", 0.0)

        band = TYPICAL.get(aircraft, TYPICAL["Sport"])
        vh_default = sum(band["vh"]) / 2.0
        vv_default = sum(band["vv"]) / 2.0
        vh_target = units.optional(inputs, "vh_target", "", vh_default) or vh_default
        vv_target = units.optional(inputs, "vv_target", "", vv_default) or vv_default

        checking = mode.startswith("Check")

        r = report.Report("Tail Volume Sizing")
        r.section("Wing Reference")
        r.value("Wing area (Sw)", wing_area, "m^2", 4)
        r.value("Span (b)", span, "m", 3)
        r.value("MAC", mac, "m", 4)
        r.value("Aspect ratio", span ** 2 / wing_area, "", 2)

        outputs = {}

        if checking:
            s_h = units.optional(inputs, "s_h", "m^2", 0.0)
            s_v = units.optional(inputs, "s_v", "m^2", 0.0)
            if s_h <= 0 and s_v <= 0:
                return report.error("Check mode needs an existing horizontal or "
                                    "vertical tail area.")

            r.section("Existing Tail")
            if s_h > 0 and l_h > 0:
                vh = (s_h * l_h) / (wing_area * mac)
                r.value("Horizontal area (Sh)", s_h, "m^2", 4)
                r.value("Horizontal arm (Lh)", l_h, "m", 3)
                r.value("Vh (referenced to MAC)", vh, "", 4)
                low, high = band["vh"]
                r.value("  typical for " + aircraft, f"{low:.2f} - {high:.2f}")
                if vh < low:
                    r.warn("Vh is below the usual range: pitch stability and "
                           "elevator authority will be marginal.")
                elif vh > high:
                    r.bullet("Vh is above the usual range. Stable, but the tail "
                             "carries weight and drag you may not need.")
                else:
                    r.bullet("Vh sits in the usual range.")
                outputs["Horizontal Tail Volume (Vh)"] = {"value": vh}

            if s_v > 0 and l_v > 0:
                vv = (s_v * l_v) / (wing_area * span)
                r.blank()
                r.value("Vertical area (Sv)", s_v, "m^2", 4)
                r.value("Vertical arm (Lv)", l_v, "m", 3)
                r.value("Vv (referenced to SPAN)", vv, "", 4)
                low, high = band["vv"]
                r.value("  typical for " + aircraft, f"{low:.3f} - {high:.3f}")
                if vv < low:
                    r.warn("Vv is below the usual range: expect weak directional "
                           "stability and poor crosswind behaviour.")
                elif vv > high:
                    r.bullet("Vv is generous. Strong weathercocking; consider "
                             "trimming area to save weight.")
                else:
                    r.bullet("Vv sits in the usual range.")
                outputs["Vertical Tail Volume (Vv)"] = {"value": vv}
        else:
            if l_h <= 0 and l_v <= 0:
                return report.error("Sizing needs at least one tail arm.")

            r.section("Target Coefficients")
            r.value("Aircraft type", aircraft)
            r.value("Target Vh", vh_target, "", 4)
            r.value("Target Vv", vv_target, "", 4)

            r.section("Required Areas")
            if l_h > 0:
                s_h = (vh_target * wing_area * mac) / l_h
                r.value("Horizontal arm (Lh)", l_h, "m", 3)
                r.value("Horizontal tail area (Sh)", s_h, "m^2", 4)
                r.value("  as % of wing area", 100.0 * s_h / wing_area, "%", 1)
                r.text("  Sh = Vh * Sw * MAC / Lh")
                outputs["Horizontal Tail Area (Sh)"] = {"value": s_h, "unit": "m^2"}

            if l_v > 0:
                s_v = (vv_target * wing_area * span) / l_v
                r.blank()
                r.value("Vertical arm (Lv)", l_v, "m", 3)
                r.value("Vertical tail area (Sv)", s_v, "m^2", 4)
                r.value("  as % of wing area", 100.0 * s_v / wing_area, "%", 1)
                r.text("  Sv = Vv * Sw * b / Lv    (span, not chord)")
                outputs["Vertical Tail Area (Sv)"] = {"value": s_v, "unit": "m^2"}

                # Show what the old chord-referenced mistake would have produced.
                wrong = (vv_target * wing_area * mac) / l_v
                if abs(wrong - s_v) / s_v > 0.2:
                    r.blank()
                    r.text(f"  Using MAC instead of span here would give "
                           f"{wrong:.4f} m^2,")
                    r.text(f"  which is {s_v / wrong:.1f}x too small.")

        r.section("Typical Volume Coefficients")
        r.table(["Type", "Vh (MAC ref)", "Vv (span ref)"],
                [[name, f"{v['vh'][0]:.2f} - {v['vh'][1]:.2f}",
                  f"{v['vv'][0]:.3f} - {v['vv'][1]:.3f}"]
                 for name, v in TYPICAL.items()])
        r.blank()
        r.text("  A longer arm buys the same stability with less area, which")
        r.text("  saves weight and drag -- but adds structure and tail-heaviness.")

        return report.result(r, outputs=outputs)

    except units.UnitError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
