"""Wing planform geometry and multirotor frame layouts."""

import math
from dataclasses import dataclass, field
from typing import List, Tuple


# ============================================================ fixed wing
@dataclass
class WingPlanform:
    span: float          # m
    area: float          # m^2
    root_chord: float    # m
    tip_chord: float     # m
    taper: float
    aspect_ratio: float
    mac: float           # mean aerodynamic chord, m
    y_mac: float         # spanwise station of the MAC, m
    x_mac_le: float      # MAC leading edge, aft of the root LE, m
    sweep_le_deg: float
    sweep_qc_deg: float
    tip_le_lag: float    # how far back the tip LE sits from the root LE, m

    @property
    def mean_chord(self) -> float:
        """Geometric mean chord S/b, which is not the same as the MAC."""
        return self.area / self.span if self.span else 0.0

    def chord_at(self, y: float) -> float:
        """Chord at a spanwise station measured from the centreline, m."""
        half = self.span / 2.0
        if half <= 0:
            return 0.0
        eta = min(abs(y) / half, 1.0)
        return self.root_chord * (1.0 - (1.0 - self.taper) * eta)

    def wetted_area(self, thickness_ratio: float = 0.12) -> float:
        """Wetted area of both surfaces, m^2. Roughly 2*S with a thickness bump."""
        return self.area * 2.0 * (1.0 + 0.25 * thickness_ratio)


def wing_from_area_ar(area: float, aspect_ratio: float, taper: float = 1.0,
                      sweep_qc_deg: float = 0.0) -> WingPlanform:
    """Build a trapezoidal planform from area, aspect ratio and taper."""
    if area <= 0 or aspect_ratio <= 0:
        raise ValueError("Wing area and aspect ratio must be greater than zero.")
    taper = max(0.01, min(taper, 1.0))

    span = math.sqrt(aspect_ratio * area)
    half_span = span / 2.0
    root_chord = 2.0 * area / (span * (1.0 + taper))
    tip_chord = root_chord * taper

    mac = (2.0 / 3.0) * root_chord * (1.0 + taper + taper ** 2) / (1.0 + taper)
    y_mac = (span / 6.0) * (1.0 + 2.0 * taper) / (1.0 + taper)

    # Quarter-chord sweep fixes where the tip sits; derive the LE sweep from it.
    sweep_qc = math.radians(sweep_qc_deg)
    tip_le_lag = half_span * math.tan(sweep_qc) - 0.25 * root_chord + 0.25 * tip_chord
    sweep_le = math.atan2(tip_le_lag, half_span)
    x_mac_le = y_mac * math.tan(sweep_le)

    return WingPlanform(
        span=span, area=area, root_chord=root_chord, tip_chord=tip_chord,
        taper=taper, aspect_ratio=aspect_ratio, mac=mac, y_mac=y_mac,
        x_mac_le=x_mac_le, sweep_le_deg=math.degrees(sweep_le),
        sweep_qc_deg=sweep_qc_deg, tip_le_lag=tip_le_lag,
    )


def wing_from_span_chord(span: float, root_chord: float, taper: float = 1.0,
                         sweep_qc_deg: float = 0.0) -> WingPlanform:
    """Build a planform from span and root chord instead."""
    if span <= 0 or root_chord <= 0:
        raise ValueError("Span and root chord must be greater than zero.")
    taper = max(0.01, min(taper, 1.0))
    area = span * root_chord * (1.0 + taper) / 2.0
    return wing_from_area_ar(area, span ** 2 / area, taper, sweep_qc_deg)


# ========================================================== multirotor
@dataclass
class FrameLayout:
    name: str
    motors: int              # total motors, counting both of a coaxial pair
    arms: int                # structural arms
    coaxial: bool
    positions: List[Tuple[float, float]] = field(default_factory=list)
    yaw_by_servo: bool = False
    notes: str = ""


# Every layout the tool suite supports. `arms` differs from `motors` for the
# coaxial (over-under) configurations, which is exactly what the old arm-length
# calculation could not express.
LAYOUTS = {
    "Tricopter":        {"motors": 3, "arms": 3, "coaxial": False, "yaw_by_servo": True,
                         "notes": "Yaw comes from tilting the rear motor, so it needs a "
                                  "servo and a tilt mechanism. Smooth in yaw, but the "
                                  "servo is a single point of failure."},
    "Quadcopter X":     {"motors": 4, "arms": 4, "coaxial": False,
                         "notes": "The default. Simple, efficient, no redundancy -- "
                                  "losing one motor means losing the aircraft."},
    "Quadcopter +":     {"motors": 4, "arms": 4, "coaxial": False,
                         "notes": "Arms aligned with the pitch and roll axes. Easier to "
                                  "reason about, but a front arm sits in the camera view."},
    "Hexacopter":       {"motors": 6, "arms": 6, "coaxial": False,
                         "notes": "Can stay airborne after a single motor failure. The "
                                  "usual choice for camera work carrying real payload."},
    "Y6":               {"motors": 6, "arms": 3, "coaxial": True,
                         "notes": "Three arms, coaxial pairs. Compact for its thrust, "
                                  "but the lower props work in the upper wash and lose "
                                  "roughly 20% efficiency."},
    "Octocopter":       {"motors": 8, "arms": 8, "coaxial": False,
                         "notes": "Maximum redundancy and thrust. Heavy, and the frame "
                                  "grows quickly with prop size."},
    "X8 (over-under)":  {"motors": 8, "arms": 4, "coaxial": True,
                         "notes": "Four arms, coaxial pairs. Octocopter thrust and "
                                  "redundancy on a quad-sized frame, at a coaxial "
                                  "efficiency penalty of about 20%."},
    "H-frame Quad":     {"motors": 4, "arms": 4, "coaxial": False,
                         "notes": "Rectangular rather than radial. Longer in one axis, "
                                  "which suits fixed forward cameras and long payloads."},
}

COAXIAL_PENALTY = 0.20  # thrust lost relative to two isolated rotors


def layout(name: str, arm_length: float = 1.0) -> FrameLayout:
    """Build a frame layout with motor positions on a unit or real arm length."""
    if name not in LAYOUTS:
        raise ValueError(f"Unknown layout '{name}'. "
                         f"Choose from: {', '.join(LAYOUTS)}.")
    spec = LAYOUTS[name]
    arms = spec["arms"]

    if name == "H-frame Quad":
        # Rectangular: arms at the corners of a box, longer fore-and-aft.
        half_x, half_y = arm_length * 0.75, arm_length * 0.55
        positions = [(half_x, half_y), (half_x, -half_y),
                     (-half_x, -half_y), (-half_x, half_y)]
    else:
        # Radial layouts sit on a regular polygon, with +X as the nose.
        # "+" puts an arm straight ahead; "X" straddles the nose; a tricopter
        # carries two forward arms and one at the tail.
        if name == "Quadcopter +":
            offset = 0.0
        elif name == "Tricopter":
            offset = math.pi / 3.0
        else:
            offset = math.pi / arms
        positions = []
        for i in range(arms):
            angle = offset + i * 2.0 * math.pi / arms
            positions.append((arm_length * math.cos(angle),
                              arm_length * math.sin(angle)))

    return FrameLayout(
        name=name, motors=spec["motors"], arms=arms, coaxial=spec["coaxial"],
        positions=positions, yaw_by_servo=spec.get("yaw_by_servo", False),
        notes=spec["notes"],
    )


def arm_length_for_clearance(rotor_diameter: float, arms: int,
                             spacing_factor: float = 1.2) -> float:
    """Arm length so adjacent rotors clear each other.

    Motors sit on a regular polygon of `arms` vertices; the chord between
    neighbours must be at least spacing_factor * rotor diameter.
    R = S / (2 * sin(pi / n))
    """
    if arms < 3:
        raise ValueError("A radial frame needs at least three arms.")
    if rotor_diameter <= 0:
        raise ValueError("Rotor diameter must be greater than zero.")
    chord = spacing_factor * rotor_diameter
    return chord / (2.0 * math.sin(math.pi / arms))


def tip_clearance(arm_length: float, arms: int, rotor_diameter: float) -> float:
    """Gap between the tips of adjacent rotors, m. Negative means overlap."""
    if arms < 3:
        return float("inf")
    chord = 2.0 * arm_length * math.sin(math.pi / arms)
    return chord - rotor_diameter


def effective_thrust(single_rotor_thrust: float, frame: FrameLayout) -> float:
    """Total frame thrust, discounting the coaxial penalty where it applies."""
    if not frame.coaxial:
        return single_rotor_thrust * frame.motors
    return single_rotor_thrust * frame.motors * (1.0 - COAXIAL_PENALTY)


def disk_count(frame: FrameLayout) -> int:
    """Number of independent rotor disks.

    Momentum theory works on swept disk area, and a coaxial pair shares one
    disk rather than adding a second. Treating an X8 as eight independent
    disks would wrongly predict it to hover more efficiently than a quad of
    the same mass and rotor size, when in reality it is worse.
    """
    return frame.arms if frame.coaxial else frame.motors


def frame_size_class(arm_length: float) -> str:
    """Hobby frame size class, quoted as motor-to-motor diagonal in mm."""
    diagonal_mm = arm_length * 2.0 * 1000.0
    for limit, label in ((150, "Micro / whoop class"),
                         (250, "Racing class (5 inch)"),
                         (400, "Sport / freestyle class (6-7 inch)"),
                         (700, "Camera platform class (10-13 inch)"),
                         (1200, "Heavy lift class (15-18 inch)")):
        if diagonal_mm < limit:
            return f"{diagonal_mm:.0f} mm diagonal - {label}"
    return f"{diagonal_mm:.0f} mm diagonal - Large heavy-lift / agricultural class"


def mixing_matrix(frame: FrameLayout) -> List[dict]:
    """Per-motor contribution to roll, pitch and yaw.

    Each motor's roll and pitch authority is its moment arm about that axis;
    yaw comes from reaction torque, so it alternates with the direction of
    rotation. Coaxial pairs share a position and spin opposite ways.
    """
    rows = []
    max_arm = max((math.hypot(x, y) for x, y in frame.positions), default=1.0) or 1.0
    motors_per_arm = frame.motors // frame.arms

    for index, (x, y) in enumerate(frame.positions):
        for level in range(motors_per_arm):
            # Roll responds to lateral offset, pitch to longitudinal offset.
            roll = -y / max_arm
            pitch = x / max_arm
            if frame.coaxial:
                # Upper and lower rotors of a pair counter-rotate.
                spin = 1.0 if level == 0 else -1.0
            else:
                spin = 1.0 if index % 2 == 0 else -1.0
            rows.append({
                "motor": len(rows) + 1,
                "arm": index + 1,
                "level": "upper" if (frame.coaxial and level == 0)
                         else "lower" if frame.coaxial else "-",
                "x": x, "y": y,
                "roll": roll, "pitch": pitch,
                "yaw": 0.0 if frame.yaw_by_servo else spin,
                "spin": "CCW" if spin > 0 else "CW",
            })
    return rows


def motor_demands(frame: FrameLayout, hover_thrust_each: float,
                  roll: float = 0.0, pitch: float = 0.0,
                  yaw: float = 0.0) -> List[dict]:
    """Per-motor thrust for a control demand, and whether any motor saturates.

    Demands are fractions of hover thrust. Saturation is the practical limit on
    how much authority a frame really has -- a motor cannot push below zero, and
    it cannot exceed its maximum thrust.
    """
    rows = mixing_matrix(frame)
    results = []
    for row in rows:
        delta = (row["roll"] * roll + row["pitch"] * pitch + row["yaw"] * yaw)
        thrust = hover_thrust_each * (1.0 + delta)
        results.append({**row, "thrust": thrust,
                        "fraction_of_hover": thrust / hover_thrust_each
                        if hover_thrust_each else 0.0})
    return results
