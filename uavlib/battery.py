"""Battery pack modelling for electric UAVs."""

import math

# Nominal, fully charged and safe-minimum cell voltages by chemistry.
CHEMISTRY = {
    "LiPo":     {"nominal": 3.7,  "full": 4.20, "empty": 3.50, "wh_per_kg": 180.0},
    "Li-ion":   {"nominal": 3.6,  "full": 4.20, "empty": 3.00, "wh_per_kg": 250.0},
    "LiHV":     {"nominal": 3.8,  "full": 4.35, "empty": 3.50, "wh_per_kg": 190.0},
    "LiFePO4":  {"nominal": 3.2,  "full": 3.65, "empty": 2.80, "wh_per_kg": 110.0},
    "NiMH":     {"nominal": 1.2,  "full": 1.45, "empty": 1.00, "wh_per_kg": 90.0},
}

# Internal resistance of one cell, in milliohm-amp-hours: divide by the cell's
# capacity in Ah to get its resistance. Bigger cells have proportionally lower
# resistance, so 20 mohm*Ah gives a 5 Ah LiPo cell 4 mohm and a 1.3 Ah cell
# 15 mohm, both of which match measured packs.
IR_MOHM_AH = {"LiPo": 20.0, "Li-ion": 100.0, "LiHV": 20.0,
              "LiFePO4": 30.0, "NiMH": 15.0}


def nominal_voltage(cells: int, chemistry: str = "LiPo") -> float:
    return cells * CHEMISTRY.get(chemistry, CHEMISTRY["LiPo"])["nominal"]


def pack_energy(voltage: float, capacity_ah: float) -> float:
    """Nameplate pack energy, Wh."""
    return voltage * capacity_ah


def usable_energy(voltage: float, capacity_ah: float,
                  depth_of_discharge: float = 0.80) -> float:
    """Energy actually available, Wh.

    Running a LiPo below about 20% remaining shortens its life sharply, so the
    usable figure -- not the nameplate -- is what sets endurance.
    """
    return pack_energy(voltage, capacity_ah) * max(0.0, min(depth_of_discharge, 1.0))


def c_rate(current_a: float, capacity_ah: float) -> float:
    """Discharge rate expressed in C."""
    if capacity_ah <= 0:
        raise ValueError("Capacity must be greater than zero.")
    return current_a / capacity_ah


def internal_resistance(cells: int, capacity_ah: float, chemistry: str = "LiPo",
                        parallel: int = 1) -> float:
    """Estimated pack internal resistance, ohms.

    Resistance scales with cell count and falls with capacity and parallel
    strings. This is an estimate; measure the real pack when it matters.
    """
    strings = max(1, parallel)
    cell_capacity = max(0.05, capacity_ah / strings)
    per_cell = IR_MOHM_AH.get(chemistry, 20.0) / 1000.0 / cell_capacity
    # Cells in series add resistance; parallel strings divide it.
    return per_cell * cells / strings


def voltage_under_load(cells: int, capacity_ah: float, current_a: float,
                       chemistry: str = "LiPo", parallel: int = 1,
                       state_of_charge: float = 0.5) -> dict:
    """Pack voltage while delivering a current.

    Sag matters twice over: it reduces available power, and it is what actually
    triggers a low-voltage cutoff mid-throttle-burst.
    """
    spec = CHEMISTRY.get(chemistry, CHEMISTRY["LiPo"])
    soc = max(0.0, min(state_of_charge, 1.0))
    open_circuit_per_cell = spec["empty"] + (spec["full"] - spec["empty"]) * soc

    resistance = internal_resistance(cells, capacity_ah, chemistry, parallel)
    sag = current_a * resistance
    open_circuit = open_circuit_per_cell * cells
    loaded = open_circuit - sag

    return {
        "open_circuit": open_circuit,
        "loaded": loaded,
        "sag": sag,
        "sag_percent": 100.0 * sag / open_circuit if open_circuit > 0 else 0.0,
        "resistance": resistance,
        "per_cell_loaded": loaded / cells if cells else 0.0,
        "heat_loss": current_a ** 2 * resistance,
    }


def mass_estimate(voltage: float, capacity_ah: float,
                  chemistry: str = "LiPo") -> float:
    """Approximate pack mass from its energy content, kg."""
    spec = CHEMISTRY.get(chemistry, CHEMISTRY["LiPo"])
    return pack_energy(voltage, capacity_ah) / spec["wh_per_kg"]


def specific_energy(voltage: float, capacity_ah: float, mass_kg: float) -> float:
    """Actual pack specific energy, Wh/kg."""
    if mass_kg <= 0:
        raise ValueError("Pack mass must be greater than zero.")
    return pack_energy(voltage, capacity_ah) / mass_kg


def endurance(usable_wh: float, average_power_w: float) -> float:
    """Flight time, minutes."""
    if average_power_w <= 0:
        raise ValueError("Average power must be greater than zero.")
    return usable_wh / average_power_w * 60.0


# American Wire Gauge: continuous current capability in a bundled, moving-air
# installation, and resistance per metre at 20 degC.
AWG_TABLE = [
    # (gauge, area mm^2, continuous amps, milliohm per metre)
    (2,  33.6, 181.0, 0.513),
    (4,  21.2, 135.0, 0.815),
    (6,  13.3, 101.0, 1.296),
    (8,  8.37, 73.0, 2.06),
    (10, 5.26, 55.0, 3.28),
    (12, 3.31, 41.0, 5.21),
    (14, 2.08, 32.0, 8.28),
    (16, 1.31, 22.0, 13.2),
    (18, 0.82, 16.0, 21.0),
    (20, 0.52, 11.0, 33.3),
    (22, 0.33, 7.0, 53.0),
    (24, 0.20, 3.5, 84.2),
]


def recommend_wire(current_a: float, margin: float = 1.25) -> dict:
    """Lightest AWG that still carries the current with margin.

    The table runs thick to thin, so it is walked in reverse: the first gauge
    that meets the target is the smallest adequate one, not the largest.
    """
    target = current_a * margin
    for gauge, area, amps, mohm in reversed(AWG_TABLE):
        if amps >= target:
            return {"awg": gauge, "area_mm2": area, "rated_a": amps,
                    "mohm_per_m": mohm, "target_a": target}
    thickest = AWG_TABLE[0]
    return {"awg": thickest[0], "area_mm2": thickest[1], "rated_a": thickest[2],
            "mohm_per_m": thickest[3], "target_a": target,
            "warning": "Current exceeds the largest tabulated gauge; "
                       "use parallel runs or busbar."}


def c_rating_note(required_c: float, rated_c: float) -> str:
    if rated_c <= 0:
        return "No pack C rating given; cannot check discharge capability."
    ratio = required_c / rated_c
    if ratio > 1.0:
        return (f"OVER LIMIT. The load needs {required_c:.0f}C from a "
                f"{rated_c:.0f}C pack. Expect severe sag, heat and cell damage.")
    if ratio > 0.8:
        return (f"Marginal. Using {ratio * 100:.0f}% of the pack's rating leaves "
                "little headroom; packs rarely meet their advertised figure.")
    if ratio > 0.5:
        return f"Comfortable. Using {ratio * 100:.0f}% of the pack's rating."
    return (f"Conservative. Only {ratio * 100:.0f}% of the pack's rating is used; "
            "a lighter, lower-C pack may save weight.")
