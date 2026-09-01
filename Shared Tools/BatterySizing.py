"""
Battery and Power System Sizing

Checks a pack against the load it has to carry: cell count, discharge rate,
voltage sag, wiring and connector losses, and the mass penalty of carrying more
energy. Sag is the part most often overlooked -- it is what actually trips a
low-voltage cutoff mid-throttle-burst, long before the pack is empty.
"""

from uavlib import battery, report, units

TOOL_METADATA = {
    "name": "Battery & Power System Sizing",
    "category": "Shared / Propulsion",
    "description": (
        "Pack energy, usable capacity, C-rate adequacy, voltage sag under load "
        "and wire gauge. Compares candidate cell counts and capacities against "
        "the current the airframe actually draws."
    ),
    "inputs": [
        {"key": "chemistry", "label": "Chemistry", "type": "choice",
         "choices": ["LiPo", "Li-ion", "LiHV", "LiFePO4", "NiMH"],
         "default": "LiPo"},
        {"key": "cells", "label": "Cells in Series (S)", "type": "number",
         "default": "4", "min": 1, "max": 24},
        {"key": "parallel", "label": "Strings in Parallel (P)", "type": "number",
         "default": "1", "min": 1, "max": 12},
        {"key": "capacity", "label": "Total Capacity", "unit": "Ah",
         "type": "number", "help": "Accepts mAh, e.g. '5000 mAh'."},
        {"key": "c_rating", "label": "Pack C Rating", "type": "number",
         "help": "Continuous rating from the label. Optional."},
        {"key": "cruise_power", "label": "Cruise / Hover Power", "unit": "W",
         "type": "number", "help": "Steady draw from the propulsion tools."},
        {"key": "peak_power", "label": "Peak Power", "unit": "W",
         "type": "number", "help": "Full-throttle draw. Optional."},
        {"key": "depth_of_discharge", "label": "Usable Capacity", "unit": "%",
         "type": "number", "default": "80"},
        {"key": "pack_mass", "label": "Measured Pack Mass", "unit": "kg",
         "type": "number", "help": "Optional. Blank uses an estimate."},
        {"key": "wire_length", "label": "Main Wire Run", "unit": "m",
         "type": "number", "default": "0.3",
         "help": "Total there-and-back length of the main power leads."},
    ],
}


def run(inputs):
    try:
        chemistry = inputs.get("chemistry") or "LiPo"
        cells = int(units.positive(inputs, "cells", "", "Cell count", default=4))
        parallel = int(units.optional(inputs, "parallel", "", 1) or 1)
        capacity = units.positive(inputs, "capacity", "Ah", "Capacity")
        c_rating = units.optional(inputs, "c_rating", "", 0.0)
        cruise_power = units.positive(inputs, "cruise_power", "W", "Cruise power")
        peak_power = units.optional(inputs, "peak_power", "W", 0.0)
        dod = units.fraction(inputs, "depth_of_discharge", 0.80)
        measured_mass = units.optional(inputs, "pack_mass", "kg", 0.0)
        wire_length = units.optional(inputs, "wire_length", "m", 0.3)

        spec = battery.CHEMISTRY[chemistry]
        voltage = battery.nominal_voltage(cells, chemistry)
        full_voltage = cells * spec["full"]
        empty_voltage = cells * spec["empty"]

        total_wh = battery.pack_energy(voltage, capacity)
        usable_wh = battery.usable_energy(voltage, capacity, dod)
        mass = measured_mass or battery.mass_estimate(voltage, capacity, chemistry)

        cruise_current = cruise_power / voltage
        peak_current = (peak_power / voltage) if peak_power > 0 else cruise_current

        r = report.Report("Battery Sizing")
        r.section("Pack")
        label = f"{cells}S{parallel}P" if parallel > 1 else f"{cells}S"
        r.value("Configuration", f"{label} {chemistry}")
        r.value("Nominal voltage", voltage, "V", 2)
        r.value("Fully charged", full_voltage, "V", 2,
                note=f"{spec['full']:.2f} V/cell")
        r.value("Safe minimum", empty_voltage, "V", 2,
                note=f"{spec['empty']:.2f} V/cell")
        r.value("Capacity", capacity, "Ah", 3)
        r.value("  in mAh", capacity * 1000, "mAh", 0)

        r.section("Energy")
        r.value("Nameplate energy", total_wh, "Wh", 1)
        r.value("Usable energy", usable_wh, "Wh", 1, note=f"{dod * 100:.0f}% DoD")
        r.dual("Pack mass", mass, "kg", "lb", 4,)
        r.value("  source", "measured" if measured_mass else "estimated")
        r.value("Specific energy", total_wh / mass if mass > 0 else 0, "Wh/kg", 1)
        r.value("Reference for " + chemistry, spec["wh_per_kg"], "Wh/kg", 0)

        r.section("Discharge")
        r.value("Cruise power", cruise_power, "W", 1)
        r.value("Cruise current", cruise_current, "A", 2)
        r.value("Cruise C rate", battery.c_rate(cruise_current, capacity), "C", 1)
        if peak_power > 0:
            r.value("Peak power", peak_power, "W", 1)
            r.value("Peak current", peak_current, "A", 2)
            r.value("Peak C rate", battery.c_rate(peak_current, capacity), "C", 1)
        if c_rating > 0:
            r.value("Pack rating", c_rating, "C", 0)
            r.value("Maximum current", c_rating * capacity, "A", 1)
            r.blank()
            r.text(f"  {battery.c_rating_note(battery.c_rate(peak_current, capacity), c_rating)}")

        r.section("Voltage Sag")
        rows = []
        for label_text, current in (("Cruise", cruise_current),
                                    ("Peak", peak_current)):
            for soc, soc_label in ((1.0, "full"), (0.5, "half"), (0.15, "low")):
                sag = battery.voltage_under_load(cells, capacity, current,
                                                 chemistry, parallel, soc)
                rows.append([label_text, soc_label, f"{sag['open_circuit']:.2f}",
                             f"{sag['loaded']:.2f}", f"{sag['sag']:.2f}",
                             f"{sag['per_cell_loaded']:.2f}"])
        r.table(["Load", "Charge", "Open V", "Loaded V", "Sag V", "V/cell"], rows)

        peak_sag = battery.voltage_under_load(cells, capacity, peak_current,
                                              chemistry, parallel, 0.15)
        r.value("Pack resistance", peak_sag["resistance"] * 1000, "mohm", 1)
        r.value("Heat at peak current", peak_sag["heat_loss"], "W", 1)

        if peak_sag["per_cell_loaded"] < spec["empty"]:
            r.warn(f"At peak current on a low pack, cells fall to "
                   f"{peak_sag['per_cell_loaded']:.2f} V, below the "
                   f"{spec['empty']:.2f} V limit. The flight controller will "
                   "trigger its low-voltage cutoff mid-manoeuvre.")
        elif peak_sag["per_cell_loaded"] < spec["empty"] + 0.15:
            r.warn("Very little margin above the cutoff voltage at peak draw "
                   "near the end of the flight.")

        r.section("Wiring")
        wire = battery.recommend_wire(peak_current)
        r.value("Recommended gauge", f"AWG {wire['awg']}", "",
                note=f"{wire['rated_a']:.0f} A rated")
        r.value("Conductor area", wire["area_mm2"], "mm^2", 2)
        resistance = wire["mohm_per_m"] / 1000.0 * wire_length
        r.value("Wire run", wire_length, "m", 2)
        r.value("Wire resistance", resistance * 1000, "mohm", 2)
        r.value("Loss at peak current", peak_current ** 2 * resistance, "W", 2)
        r.value("Voltage drop in wiring", peak_current * resistance, "V", 3)
        if "warning" in wire:
            r.warn(wire["warning"])
        r.blank()
        r.text("  Gauge ratings here are conservative continuous figures. Short")
        r.text("  runs with good airflow tolerate more, but connectors and")
        r.text("  solder joints often limit the system before the wire does.")

        r.section("Trade-offs")
        r.text("  Doubling capacity never doubles flight time, because the")
        r.text("  extra mass raises the power required. Compare candidates:")
        r.blank()
        rows = []
        for factor in (0.5, 0.75, 1.0, 1.5, 2.0):
            cap = capacity * factor
            pack_mass = battery.mass_estimate(voltage, cap, chemistry)
            energy = battery.usable_energy(voltage, cap, dod)
            minutes = energy / cruise_power * 60.0
            rows.append([f"{cap * 1000:.0f} mAh", f"{pack_mass * 1000:.0f} g",
                         f"{energy:.1f}", f"{minutes:.1f}",
                         "<-- current" if abs(factor - 1.0) < 1e-9 else ""])
        r.table(["Capacity", "Mass", "Usable Wh", "Minutes", ""], rows)
        r.text("  These minutes assume the airframe mass is unchanged. Feed the")
        r.text("  new all-up mass back through the endurance tool for the real")
        r.text("  answer -- the gain is always smaller than it looks here.")

        return report.result(r, outputs={
            "Battery Voltage": {"value": voltage, "unit": "V"},
            "Battery Capacity": {"value": capacity, "unit": "Ah"},
            "Usable Energy": {"value": usable_wh, "unit": "Wh"},
            "Pack Mass": {"value": mass, "unit": "kg"},
            "Peak Current": {"value": peak_current, "unit": "A"},
        })

    except units.UnitError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
