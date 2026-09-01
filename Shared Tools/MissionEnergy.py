"""
Mission Energy Profile

Adds up the energy a whole flight actually costs, segment by segment, rather
than assuming steady cruise for the entire pack. Climbs are expensive and
reserves are not optional, so a mission that looks feasible on a cruise-only
endurance figure often is not.

Segments are entered one per line as:

    name, minutes, power

Power accepts watts directly, or a multiple of the cruise power written as
``1.4x`` -- handy because hover, climb and loiter are usually quoted relative
to cruise.
"""

from uavlib import battery, plotting, report, units

TOOL_METADATA = {
    "name": "Mission Energy Profile",
    "category": "Shared / Mission",
    "description": (
        "Energy budget across a mission's segments, with reserve, against the "
        "pack's usable capacity. Reports the feasibility margin and the "
        "smallest pack that would complete the mission."
    ),
    "inputs": [
        {"key": "segments", "label": "Mission Segments", "type": "text",
         "help": "One per line: name, minutes, power. Power may be watts "
                 "(180 W) or a multiple of cruise (1.4x)."},
        {"key": "cruise_power", "label": "Cruise / Hover Power", "unit": "W",
         "type": "number", "help": "Reference for the 'x' multipliers."},
        {"key": "cells", "label": "Battery Cells (S)", "type": "number",
         "default": "4"},
        {"key": "chemistry", "label": "Chemistry", "type": "choice",
         "choices": ["LiPo", "Li-ion", "LiHV", "LiFePO4", "NiMH"],
         "default": "LiPo"},
        {"key": "capacity", "label": "Battery Capacity", "unit": "Ah",
         "type": "number", "help": "Accepts mAh."},
        {"key": "depth_of_discharge", "label": "Usable Capacity", "unit": "%",
         "type": "number", "default": "80"},
        {"key": "reserve_minutes", "label": "Reserve", "unit": "min",
         "type": "number", "default": "3",
         "help": "Held back at cruise power for a go-around or diversion."},
    ],
}

EXAMPLE = """Takeoff and climb, 1.5, 2.2x
Transit out, 4, 1.1x
Survey loiter, 12, 0.9x
Transit back, 4, 1.1x
Descent and land, 2, 0.5x"""


def parse_segments(text, cruise_power):
    rows, errors = [], []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            errors.append(f"Line {number}: need 'name, minutes, power'.")
            continue
        name = parts[0]
        try:
            minutes = units.parse(parts[1], "", None)
        except units.UnitError as exc:
            errors.append(f"Line {number}: {exc}")
            continue
        if minutes is None or minutes <= 0:
            errors.append(f"Line {number}: duration must be positive.")
            continue

        power_text = parts[2].lower().replace(" ", "")
        try:
            if power_text.endswith("x"):
                power = float(power_text[:-1]) * cruise_power
            else:
                power = units.parse(parts[2], "W", None)
        except (ValueError, units.UnitError):
            errors.append(f"Line {number}: could not read the power value.")
            continue
        if power is None or power < 0:
            errors.append(f"Line {number}: power must be zero or more.")
            continue

        rows.append({"name": name, "minutes": minutes, "power": power,
                     "wh": power * minutes / 60.0})
    return rows, errors


def run(inputs):
    try:
        text = (inputs.get("segments") or "").strip()
        cruise_power = units.parse(inputs.get("cruise_power"), "W", None)

        if not text or not cruise_power:
            r = report.Report("Mission Energy Profile")
            r.text("  Enter one segment per line as:")
            r.text("")
            r.text("      name, minutes, power")
            r.text("")
            r.text("  Power may be given in watts, or as a multiple of the")
            r.text("  cruise power -- '2.2x' for a climb, '0.9x' for a loiter.")
            r.blank()
            r.section("Example")
            for line in EXAMPLE.splitlines():
                r.text(f"      {line}")
            r.blank()
            r.text("  Cruise / hover power is required so the multipliers have")
            r.text("  something to refer to.")
            return str(r)

        cells = int(units.positive(inputs, "cells", "", "Cell count", default=4))
        chemistry = inputs.get("chemistry") or "LiPo"
        capacity = units.positive(inputs, "capacity", "Ah", "Battery capacity")
        dod = units.fraction(inputs, "depth_of_discharge", 0.80)
        reserve_minutes = units.optional(inputs, "reserve_minutes", "", 3.0)

        segments, errors = parse_segments(text, cruise_power)
        if not segments:
            return report.error("no valid segments.\n  " + "\n  ".join(errors))

        voltage = battery.nominal_voltage(cells, chemistry)
        usable_wh = battery.usable_energy(voltage, capacity, dod)

        mission_wh = sum(s["wh"] for s in segments)
        mission_minutes = sum(s["minutes"] for s in segments)
        reserve_wh = cruise_power * reserve_minutes / 60.0
        required_wh = mission_wh + reserve_wh
        margin_wh = usable_wh - required_wh

        r = report.Report("Mission Energy Profile")

        if errors:
            r.section("Skipped Lines")
            for message in errors:
                r.warn(message)

        r.section("Segments")
        rows = []
        cumulative = 0.0
        for s in segments:
            cumulative += s["wh"]
            rows.append([s["name"][:22], f"{s['minutes']:.1f}",
                         f"{s['power']:.0f}", f"{s['power'] / cruise_power:.2f}x",
                         f"{s['wh']:.2f}", f"{cumulative:.2f}",
                         f"{100 * cumulative / usable_wh:.0f}%"])
        r.table(["Segment", "Min", "Watts", "vs cruise", "Wh", "Cumul.",
                 "% pack"], rows)

        r.section("Budget")
        r.value("Cruise reference power", cruise_power, "W", 1)
        r.value("Mission duration", mission_minutes, "minutes", 1)
        r.value("Mission energy", mission_wh, "Wh", 2)
        r.value("Reserve", reserve_wh, "Wh", 2,
                note=f"{reserve_minutes:g} min at cruise")
        r.value("Total required", required_wh, "Wh", 2)
        r.blank()
        r.value("Pack", f"{cells}S {chemistry} {capacity * 1000:.0f} mAh")
        r.value("Nameplate energy", battery.pack_energy(voltage, capacity), "Wh", 2)
        r.value("Usable energy", usable_wh, "Wh", 2, note=f"{dod * 100:.0f}% DoD")
        r.value("Margin", margin_wh, "Wh", 2)
        r.value("Pack utilisation", 100 * required_wh / usable_wh, "%", 1)

        r.section("Verdict")
        if margin_wh < 0:
            shortfall = -margin_wh
            r.warn(f"NOT FEASIBLE. The mission needs {shortfall:.1f} Wh more "
                   "than the pack can usefully deliver.")
            needed_ah = required_wh / voltage / dod
            r.value("Capacity required", needed_ah * 1000, "mAh", 0)
            r.value("  versus fitted", capacity * 1000, "mAh", 0)
            r.value("Extra pack mass", battery.mass_estimate(
                voltage, needed_ah - capacity, chemistry) * 1000, "g", 0)
            r.bullet("Adding that pack mass raises the power required, so "
                     "re-run the endurance tool with the new all-up mass "
                     "before committing.")
        elif margin_wh < usable_wh * 0.1:
            r.warn(f"Feasible but tight: only {margin_wh:.1f} Wh spare "
                   f"({100 * margin_wh / usable_wh:.0f}% of the pack). Wind or "
                   "a colder day could erase this.")
        else:
            r.bullet(f"Feasible with {margin_wh:.1f} Wh spare "
                     f"({100 * margin_wh / usable_wh:.0f}% of usable capacity).")
            extra = margin_wh / cruise_power * 60.0
            r.bullet(f"That is about {extra:.1f} extra minutes at cruise power.")

        heaviest = max(segments, key=lambda s: s["wh"])
        r.blank()
        r.bullet(f"'{heaviest['name']}' is the largest single draw at "
                 f"{heaviest['wh']:.1f} Wh "
                 f"({100 * heaviest['wh'] / mission_wh:.0f}% of the mission).")

        r.section("Smallest Adequate Pack")
        rows = []
        for cap in (capacity * f for f in (0.6, 0.8, 1.0, 1.2, 1.5)):
            available = battery.usable_energy(voltage, cap, dod)
            ok = "yes" if available >= required_wh else "NO"
            rows.append([f"{cap * 1000:.0f} mAh",
                         f"{battery.mass_estimate(voltage, cap, chemistry) * 1000:.0f}",
                         f"{available:.1f}", ok])
        r.table(["Capacity", "Mass g", "Usable Wh", "Sufficient"], rows)

        figures = []
        if plotting.available():
            try:
                figures.append(plotting.bar_chart(
                    "Energy by Segment", "Energy (Wh)", "",
                    [s["name"] for s in segments] + ["Reserve"],
                    [s["wh"] for s in segments] + [reserve_wh]))
                times, remaining = [0.0], [usable_wh]
                clock, left = 0.0, usable_wh
                for s in segments:
                    clock += s["minutes"]
                    left -= s["wh"]
                    times.append(clock)
                    remaining.append(left)
                figures.append(plotting.line_chart(
                    "Energy Remaining", "Mission time (min)",
                    "Usable energy remaining (Wh)",
                    [("Remaining", times, remaining),
                     ("Reserve floor", [0, clock], [reserve_wh, reserve_wh])]))
            except Exception:
                r.note("Charts could not be generated.")

        return report.result(r, outputs={
            "Mission Duration": {"value": mission_minutes, "unit": "min"},
            "Mission Energy": {"value": required_wh, "unit": "Wh"},
            "Energy Margin": {"value": margin_wh, "unit": "Wh"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
