"""
Electrical Current Budget

Adds up every consumer on the airframe and checks the total against the
battery, ESC, BEC and wiring. The propulsion draw is obvious; what catches
people out is the accumulated avionics load on the BEC, which is often rated
for far less than the servos and payload actually pull when they all move at
once.

Consumers are entered one per line as:

    name, current or power [, quantity] [, bec]

Append ``bec`` to mark a consumer as fed from the BEC rather than directly from
the main pack.
"""

from uavlib import battery, plotting, report, units

TOOL_METADATA = {
    "name": "Electrical Current Budget",
    "category": "Shared / Propulsion",
    "description": (
        "Totals propulsion, avionics and payload current against the pack, "
        "ESC, BEC and wiring limits. Reports headroom on each and the pack "
        "C-rate the combination demands."
    ),
    "inputs": [
        {"key": "consumers", "label": "Consumers", "type": "text",
         "help": "One per line: name, current or power [, quantity] [, bec]. "
                 "Example: Servo, 0.8 A, 4, bec"},
        {"key": "propulsion_current", "label": "Propulsion Current", "unit": "A",
         "type": "number", "help": "Peak draw from the propulsion tools."},
        {"key": "cells", "label": "Battery Cells (S)", "type": "number",
         "default": "4"},
        {"key": "capacity", "label": "Battery Capacity", "unit": "Ah",
         "type": "number", "help": "Accepts mAh."},
        {"key": "pack_c_rating", "label": "Pack C Rating", "type": "number",
         "help": "Optional."},
        {"key": "esc_rating", "label": "ESC Rating", "unit": "A",
         "type": "number", "help": "Optional. Per ESC."},
        {"key": "esc_count", "label": "Number of ESCs", "type": "number",
         "default": "1"},
        {"key": "bec_rating", "label": "BEC Rating", "unit": "A",
         "type": "number", "default": "3",
         "help": "Continuous rating of the 5 V supply."},
        {"key": "bec_voltage", "label": "BEC Voltage", "unit": "V",
         "type": "number", "default": "5"},
    ],
}

EXAMPLE = """Receiver, 0.1 A, 1, bec
Servo, 0.8 A, 4, bec
Flight controller, 0.25 A, 1, bec
FPV transmitter, 4.2 W, 1
Camera, 1.8 W, 1
GPS, 0.05 A, 1, bec"""


def parse_consumers(text, pack_voltage, bec_voltage):
    rows, errors = [], []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            errors.append(f"Line {number}: need 'name, current or power'.")
            continue

        name = parts[0]
        on_bec = any(p.lower() in ("bec", "5v") for p in parts[2:])
        quantity = 1
        for candidate in parts[2:]:
            if candidate.lower() in ("bec", "5v"):
                continue
            try:
                quantity = max(1, int(float(candidate)))
                break
            except ValueError:
                continue

        supply = bec_voltage if on_bec else pack_voltage
        value_text = parts[1].lower().replace(" ", "")
        try:
            if value_text.endswith("w"):
                power = units.parse(parts[1], "W", None)
                current = power / supply if supply > 0 else 0.0
            else:
                current = units.parse(parts[1], "", None)
                power = current * supply
        except units.UnitError as exc:
            errors.append(f"Line {number}: {exc}")
            continue
        if current is None:
            errors.append(f"Line {number}: could not read the value.")
            continue

        rows.append({"name": name, "quantity": quantity, "on_bec": on_bec,
                     "current_each": current, "current": current * quantity,
                     "power": power * quantity})
    return rows, errors


def run(inputs):
    try:
        text = (inputs.get("consumers") or "").strip()
        cells = int(units.positive(inputs, "cells", "", "Cell count", default=4))
        bec_voltage = units.optional(inputs, "bec_voltage", "V", 5.0) or 5.0
        pack_voltage = battery.nominal_voltage(cells, "LiPo")

        if not text:
            r = report.Report("Electrical Current Budget")
            r.text("  Enter one consumer per line as:")
            r.text("")
            r.text("      name, current or power [, quantity] [, bec]")
            r.text("")
            r.text("  Append 'bec' when the item is fed from the 5 V BEC rather")
            r.text("  than the main pack. Quantity defaults to 1.")
            r.blank()
            r.section("Example")
            for line in EXAMPLE.splitlines():
                r.text(f"      {line}")
            return str(r)

        propulsion = units.optional(inputs, "propulsion_current", "A", 0.0)
        capacity = units.optional(inputs, "capacity", "Ah", 0.0)
        pack_c = units.optional(inputs, "pack_c_rating", "", 0.0)
        esc_rating = units.optional(inputs, "esc_rating", "A", 0.0)
        esc_count = int(units.optional(inputs, "esc_count", "", 1) or 1)
        bec_rating = units.optional(inputs, "bec_rating", "A", 3.0)

        rows, errors = parse_consumers(text, pack_voltage, bec_voltage)
        if not rows and not propulsion:
            return report.error("no valid consumers.\n  " + "\n  ".join(errors))

        bec_current = sum(row["current"] for row in rows if row["on_bec"])
        direct_current = sum(row["current"] for row in rows if not row["on_bec"])
        bec_power = sum(row["power"] for row in rows if row["on_bec"])
        # BEC losses come out of the main pack.
        bec_pack_current = bec_power / (pack_voltage * 0.85) if pack_voltage else 0
        total_pack = propulsion + direct_current + bec_pack_current

        r = report.Report("Electrical Current Budget")

        if errors:
            r.section("Skipped Lines")
            for message in errors:
                r.warn(message)

        r.section("Consumers")
        table_rows = []
        for row in sorted(rows, key=lambda row: -row["current"]):
            table_rows.append([
                row["name"][:22], f"{row['quantity']}",
                "BEC" if row["on_bec"] else "pack",
                f"{row['current_each']:.3f}", f"{row['current']:.3f}",
                f"{row['power']:.2f}"])
        if table_rows:
            r.table(["Consumer", "Qty", "Supply", "A each", "A total", "W"],
                    table_rows)

        r.section("Totals")
        r.value("Pack voltage", pack_voltage, "V", 2, note=f"{cells}S nominal")
        r.value("Propulsion current", propulsion, "A", 2)
        r.value("Direct pack loads", direct_current, "A", 3)
        r.value("BEC loads (at 5 V)", bec_current, "A", 3)
        r.value("BEC power", bec_power, "W", 2)
        r.value("BEC draw from pack", bec_pack_current, "A", 3,
                note="85% converter efficiency")
        r.blank()
        r.value("TOTAL PACK CURRENT", total_pack, "A", 2)
        r.value("Total power", total_pack * pack_voltage, "W", 1)

        r.section("Limit Checks")
        if bec_rating > 0:
            r.value("BEC rating", bec_rating, "A", 2)
            r.value("BEC load", bec_current, "A", 3)
            r.value("BEC headroom", 100 * (1 - bec_current / bec_rating), "%", 1)
            if bec_current > bec_rating:
                r.warn(f"BEC OVERLOADED: {bec_current:.2f} A drawn from a "
                       f"{bec_rating:.1f} A supply. The BEC will brown out, and "
                       "a brown-out means loss of control.")
            elif bec_current > bec_rating * 0.7:
                r.warn("Using more than 70% of the BEC rating. Servos draw far "
                       "more than their idle figure when they stall against a "
                       "load, so the peak is well above this total.")
            else:
                r.bullet("BEC load is comfortable.")
            r.bullet("Servo stall current can be 3-5 times the running figure. "
                     "If several servos hit their end stops together, the "
                     "instantaneous draw dwarfs this budget.")

        if esc_rating > 0:
            per_esc = propulsion / max(1, esc_count)
            r.blank()
            r.value("ESC rating (each)", esc_rating, "A", 1)
            r.value("Current per ESC", per_esc, "A", 2)
            r.value("ESC headroom", 100 * (1 - per_esc / esc_rating), "%", 1)
            if per_esc > esc_rating:
                r.warn("ESC over its rating; it will overheat and fail.")
            elif per_esc > esc_rating * 0.8:
                r.warn("Above 80% of the ESC rating leaves little thermal "
                       "margin.")
            else:
                r.bullet("ESC current is within a sensible margin.")

        if capacity > 0:
            required_c = battery.c_rate(total_pack, capacity)
            r.blank()
            r.value("Pack capacity", capacity, "Ah", 3)
            r.value("Required C rate", required_c, "C", 1)
            if pack_c > 0:
                r.value("Pack rating", pack_c, "C", 0)
                r.text(f"  {battery.c_rating_note(required_c, pack_c)}")
            sag = battery.voltage_under_load(cells, capacity, total_pack, "LiPo",
                                             state_of_charge=0.3)
            r.value("Voltage at 30% charge", sag["loaded"], "V", 2,
                    note=f"sag {sag['sag_percent']:.1f}%")
            r.value("Per cell", sag["per_cell_loaded"], "V", 2)
            if sag["per_cell_loaded"] < 3.4:
                r.warn("Cells drop below 3.4 V under this load on a low pack. "
                       "Expect the low-voltage alarm mid-flight.")
            r.value("Runtime at this draw",
                    battery.usable_energy(pack_voltage, capacity)
                    / (total_pack * pack_voltage) * 60, "minutes", 1)

        wire = battery.recommend_wire(total_pack)
        r.blank()
        r.value("Main wire gauge", f"AWG {wire['awg']}", "",
                note=f"{wire['rated_a']:.0f} A rated")
        if "warning" in wire:
            r.warn(wire["warning"])

        figures = []
        if plotting.available() and rows:
            try:
                labels = [row["name"] for row in rows]
                values = [row["current"] for row in rows]
                if propulsion > 0:
                    labels.append("Propulsion")
                    values.append(propulsion)
                figures.append(plotting.bar_chart(
                    "Current by Consumer", "Current (A)", "", labels, values))
            except Exception:
                r.note("Chart could not be generated.")

        return report.result(r, outputs={
            "Total Pack Current": {"value": total_pack, "unit": "A"},
            "BEC Current": {"value": bec_current, "unit": "A"},
            "Avionics Power": {"value": bec_power + direct_current * pack_voltage,
                               "unit": "W"},
        }, figures=figures)

    except units.UnitError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
