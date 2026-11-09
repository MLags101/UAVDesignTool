"""Supersonic and transonic aerodynamics for conceptual design, to Mach 2.

Methods
-------
* Airfoils: Ackeret linear theory and exact shock-expansion (diamond section).
* Wing lift-curve slope: Helmbold/DATCOM below Mach 0.9; above Mach 1.2 the
  linear-theory result for the leading-edge regime -- delta-wing (elliptic
  integral) theory for subsonic leading edges, 4/beta with a Mach-cone tip
  loss for supersonic leading edges. A C1 cubic bridges the transonic gap.
* Drag due to lift: leading-edge-suction blend between the fully attached
  1/(pi A e) and the no-suction 1/CL_alpha (Raymer section 12.6).
* Zero-lift drag: component build-up with Raymer's compressible turbulent
  skin friction and roughness cut-off, plus wave drag. Below Mach 1 the wave
  drag follows Lock's fourth-power law from the Korn drag-divergence Mach;
  above Mach 1.2 it is the Sears-Haack drag scaled by Raymer's empirical
  E_WD factor (eq. 12.45); a monotone cubic fairs the transonic hump.

Linear theory is least reliable between Mach 0.9 and 1.2; results there carry
a warning. Everything is SI, angles are degrees where a name ends in ``_deg``.
"""

import math
from dataclasses import dataclass, field

from . import aero, area_rule, atmosphere, compressible
from .area_rule import pchip_slopes

MACH_LIMIT = 2.0
TRANSONIC = (0.9, 1.2)       # Mach band bridged by cubic fairing
SMOOTH_PAINT = 6.34e-6       # surface roughness, m (Raymer table 12.5)
MDD_CAP = 0.97               # whole-configuration drag divergence ceiling


def check_mach(mach):
    if not math.isfinite(mach) or mach < 0:
        raise ValueError("Mach number must be non-negative.")
    if mach > MACH_LIMIT + 1e-9:
        raise ValueError(f"Mach {mach:.2f} is above the Mach {MACH_LIMIT:g} model ceiling.")


def transonic_warning(mach):
    lo, hi = TRANSONIC
    if lo < mach < hi:
        return (f"Mach {mach:.2f} is in the transonic band ({lo}-{hi}); values there are a "
                "faired interpolation, not a theory result.")
    return ""


def _hermite(m, lo, hi, f_lo, f_hi, step=1e-4):
    """C1 cubic between a subsonic function at ``lo`` and a supersonic one at ``hi``."""
    y0, y1 = f_lo(lo), f_hi(hi)
    d0 = (f_lo(lo) - f_lo(lo - step)) / step
    d1 = (f_hi(hi + step) - f_hi(hi)) / step
    h = hi - lo
    t = (m - lo) / h
    return ((2 * t ** 3 - 3 * t ** 2 + 1) * y0 + (t ** 3 - 2 * t ** 2 + t) * h * d0
            + (-2 * t ** 3 + 3 * t ** 2) * y1 + (t ** 3 - t ** 2) * h * d1)


def bridged(m, subsonic, supersonic, band=TRANSONIC):
    lo, hi = band
    if m <= lo:
        return subsonic(m)
    if m >= hi:
        return supersonic(m)
    return _hermite(m, lo, hi, subsonic, supersonic)


def _smoothstep(x, lo, hi):
    t = min(max((x - lo) / (hi - lo), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def beta(mach):
    """Prandtl-Glauert factor sqrt(|M^2 - 1|)."""
    return math.sqrt(abs(mach ** 2 - 1.0))


# ------------------------------------------------------------------ airfoils
THICKNESS_FACTOR = {"diamond": 4.0, "biconvex": 16.0 / 3.0}


def airfoil_linear(mach, alpha_deg, thickness_ratio, section="biconvex"):
    """Ackeret (linear) supersonic airfoil coefficients per unit chord."""
    if mach <= 1.0:
        raise ValueError("Linear supersonic theory needs Mach > 1.")
    if section not in THICKNESS_FACTOR:
        raise ValueError(f"Section must be one of {', '.join(THICKNESS_FACTOR)}.")
    b = beta(mach)
    alpha = math.radians(alpha_deg)
    cd_lift = 4.0 * alpha ** 2 / b
    cd_thickness = THICKNESS_FACTOR[section] * thickness_ratio ** 2 / b
    return {"cl": 4.0 * alpha / b, "cd": cd_lift + cd_thickness, "cd_lift": cd_lift,
            "cd_thickness": cd_thickness, "cl_alpha_per_rad": 4.0 / b,
            "x_cp_chord": 0.5 if alpha else None}


def diamond_shock_expansion(mach, alpha_deg, thickness_ratio, gamma=1.4):
    """Exact inviscid coefficients of a symmetric diamond airfoil (shock-expansion).

    Returns the four panel pressure coefficients as well, ordered upper-front,
    upper-rear, lower-front, lower-rear.
    """
    if mach <= 1.0:
        raise ValueError("Shock-expansion theory needs Mach > 1.")
    eps = math.atan(thickness_ratio)
    alpha = math.radians(alpha_deg)
    q_ratio = 0.5 * gamma * mach ** 2
    panels = []
    for sign in (1, -1):                       # upper, lower surface
        front = compressible.turn(mach, eps - sign * alpha, gamma)
        rear = compressible.turn(front["M2"], -2 * eps, gamma)
        p_front = front["p2/p1"]
        p_rear = p_front * rear["p2/p1"]
        panels.append((sign, p_front, p_rear))
    length = 0.5 / math.cos(eps)               # panel length on a unit chord
    normal = axial = 0.0
    cps = []
    for sign, p_front, p_rear in panels:
        for p, slope in ((p_front, eps), (p_rear, -eps)):
            cp = (p - 1.0) / q_ratio
            cps.append(cp)
            # Outward normal of a panel on surface ``sign`` with slope ``slope``.
            nx, ny = -math.sin(slope), sign * math.cos(slope)
            normal -= cp * length * ny
            axial -= cp * length * nx
    cl = normal * math.cos(alpha) - axial * math.sin(alpha)
    cd = normal * math.sin(alpha) + axial * math.cos(alpha)
    return {"cl": cl, "cd": cd, "cp_panels": cps}


# --------------------------------------------------------------------- wings
def sweep_at(chord_fraction, le_sweep_deg, aspect_ratio, taper):
    """Sweep of the chord-fraction line of a straight-tapered wing, degrees."""
    tan_le = math.tan(math.radians(le_sweep_deg))
    return math.degrees(math.atan(tan_le - 4.0 * chord_fraction * (1.0 - taper)
                                  / (aspect_ratio * (1.0 + taper))))


def elliptic_e(k):
    """Complete elliptic integral of the second kind, E(k), by Simpson's rule."""
    n = 200
    h = 0.5 * math.pi / n
    total = 0.0
    for i in range(n + 1):
        w = 1 if i in (0, n) else (4 if i % 2 else 2)
        total += w * math.sqrt(1.0 - (k * math.sin(i * h)) ** 2)
    return total * h / 3.0


def leading_edge_parameter(mach, le_sweep_deg):
    """m = beta * cot(LE sweep). m < 1 is a subsonic leading edge."""
    tan_le = math.tan(math.radians(le_sweep_deg))
    return math.inf if tan_le <= 1e-12 else beta(mach) / tan_le


def _lift_slope_subsonic(mach, aspect_ratio, half_chord_sweep_deg, eta=0.95):
    b2 = max(1.0 - mach ** 2, 0.0)
    tan2 = math.tan(math.radians(half_chord_sweep_deg)) ** 2
    root = math.sqrt(4.0 + aspect_ratio ** 2 * (b2 + tan2) / eta ** 2)
    return 2.0 * math.pi * aspect_ratio / (2.0 + root)


def _lift_slope_supersonic(mach, aspect_ratio, le_sweep_deg, taper):
    b = beta(mach)
    tip_loss = min(0.5, 2.0 * taper ** 2 / (aspect_ratio * b * (1.0 + taper) ** 2))
    supersonic_edge = 4.0 / b * (1.0 - tip_loss)
    m = leading_edge_parameter(mach, le_sweep_deg)
    if m >= 1.15:
        return supersonic_edge
    k = math.sqrt(max(0.0, 1.0 - min(m, 1.0) ** 2))
    subsonic_edge = math.pi * aspect_ratio / (2.0 * elliptic_e(k))
    s = _smoothstep(m, 0.85, 1.15)
    return (1 - s) * subsonic_edge + s * supersonic_edge


def wing_lift_slope(mach, aspect_ratio, le_sweep_deg=0.0, taper=0.5):
    """3-D wing lift-curve slope per radian, Mach 0 to 2."""
    check_mach(mach)
    if aspect_ratio <= 0:
        raise ValueError("Aspect ratio must be positive.")
    half = sweep_at(0.5, le_sweep_deg, aspect_ratio, taper)
    return bridged(mach, lambda m: _lift_slope_subsonic(m, aspect_ratio, half),
                   lambda m: _lift_slope_supersonic(m, aspect_ratio, le_sweep_deg, taper))


def induced_drag_factor(mach, aspect_ratio, le_sweep_deg=0.0, taper=0.5,
                        suction_supersonic=0.25):
    """K in CD = CD0 + K CL^2, Mach 0 to 2.

    Subsonic: 1/(pi A e). Supersonic: no-suction 1/CL_alpha for a supersonic
    leading edge; for a subsonic leading edge the stated fraction of leading-edge
    suction is recovered (sharp thin edges ~0.1-0.3, rounded edges higher).
    """
    check_mach(mach)
    quarter = sweep_at(0.25, le_sweep_deg, aspect_ratio, taper)
    oswald = aero.oswald_efficiency(aspect_ratio, quarter)
    k_full = 1.0 / (math.pi * aspect_ratio * oswald)

    def supersonic(m):
        k_zero = 1.0 / _lift_slope_supersonic(m, aspect_ratio, le_sweep_deg, taper)
        s = suction_supersonic * (1.0 - _smoothstep(leading_edge_parameter(m, le_sweep_deg), 0.85, 1.15))
        return s * k_full + (1.0 - s) * max(k_zero, k_full)

    return bridged(mach, lambda m: k_full, supersonic)


def aerodynamic_center(mach, supersonic_fraction=0.45):
    """Wing aerodynamic centre as a fraction of MAC aft of the MAC leading edge.

    0.25 subsonic, moving aft to ``supersonic_fraction`` (linear theory gives
    0.5 for a supersonic edge; tip relief brings real wings to ~0.4-0.5).
    """
    check_mach(mach)
    return bridged(mach, lambda m: 0.25, lambda m: supersonic_fraction)


# ----------------------------------------------------------- zero-lift drag
def skin_friction(reynolds, mach, length, roughness=SMOOTH_PAINT, laminar_fraction=0.0):
    """Raymer flat-plate skin friction with compressibility and roughness cut-off."""
    if reynolds <= 0 or length <= 0:
        raise ValueError("Reynolds number and length must be positive.")
    if roughness > 0:
        ratio = (length / roughness) ** 1.053
        subsonic_cut = 38.21 * ratio
        supersonic_cut = 44.62 * ratio * max(mach, 1.0) ** 1.16
        f = min(max((mach - 0.9) / 0.1, 0.0), 1.0)
        reynolds = min(reynolds, (1 - f) * subsonic_cut + f * supersonic_cut)
    turbulent = 0.455 / (math.log10(reynolds) ** 2.58 * (1.0 + 0.144 * mach ** 2) ** 0.65)
    laminar = 1.328 / math.sqrt(reynolds)
    f = min(max(laminar_fraction, 0.0), 1.0)
    return f * laminar + (1.0 - f) * turbulent


def drag_divergence_mach(thickness_ratio, cl=0.0, sweep_deg=0.0, korn=0.87):
    """Korn equation. korn = 0.87 conventional sections, 0.95 supercritical."""
    c = math.cos(math.radians(sweep_deg))
    return korn / c - thickness_ratio / c ** 2 - cl / (10.0 * c ** 3)


def critical_mach(m_dd):
    """Drag-rise onset by Lock's law: dCD/dM = 0.1 at M_DD with CD = 20 (M - Mcr)^4."""
    return m_dd - (0.1 / 80.0) ** (1.0 / 3.0)


def supersonic_wave_dq(mach, dq_sears_haack, e_wd=1.8, le_sweep_deg=0.0):
    """Raymer eq. 12.45: wave D/q for M >= 1.2 from the Sears-Haack value.

    E_WD ~1.2 for a carefully area-ruled design, 1.8-2.2 for typical fighters,
    2.5-3 for blunt or poorly area-ruled shapes.
    """
    if mach < 1.2:
        raise ValueError("Raymer's wave drag fit applies from Mach 1.2.")
    sweep_term = 1.0 - math.pi * max(le_sweep_deg, 0.0) ** 0.77 / 100.0
    return e_wd * (1.0 - 0.386 * (mach - 1.2) ** 0.57 * sweep_term) * dq_sears_haack


def _pchip_eval(xs, ys, x):
    slopes = pchip_slopes(xs, ys)
    j = 0
    while j < len(xs) - 2 and x > xs[j + 1]:
        j += 1
    h = xs[j + 1] - xs[j]
    t = (x - xs[j]) / h
    return ((2 * t ** 3 - 3 * t ** 2 + 1) * ys[j] + (t ** 3 - 2 * t ** 2 + t) * h * slopes[j]
            + (-2 * t ** 3 + 3 * t ** 2) * ys[j + 1] + (t ** 3 - t ** 2) * h * slopes[j + 1])


def wave_drag_coefficient(mach, dq_sears_haack, reference_area, thickness_ratio,
                          quarter_sweep_deg=0.0, le_sweep_deg=0.0, e_wd=1.8, korn=0.87, cl=0.0,
                          m_dd=None):
    """Zero-lift wave drag coefficient on ``reference_area`` from Mach 0 to 2.

    Korn's drag divergence uses the quarter-chord sweep; Raymer's supersonic
    fit uses the leading-edge sweep.
    """
    check_mach(mach)
    if m_dd is None:
        m_dd = min(MDD_CAP, drag_divergence_mach(thickness_ratio, cl, quarter_sweep_deg, korn))
    m_cr = critical_mach(m_dd)
    if mach <= m_cr:
        return 0.0
    cd_dd = 20.0 * (m_dd - m_cr) ** 4
    if mach <= m_dd:
        return 20.0 * (mach - m_cr) ** 4
    cd_12 = supersonic_wave_dq(1.2, dq_sears_haack, e_wd, le_sweep_deg) / reference_area
    if mach >= 1.2:
        return supersonic_wave_dq(mach, dq_sears_haack, e_wd, le_sweep_deg) / reference_area
    if m_dd >= 1.05:
        return cd_dd + (cd_12 - cd_dd) * _smoothstep(mach, m_dd, 1.2)
    xs = [m_cr, m_dd, 1.05, 1.2]
    ys = [0.0, cd_dd, max(cd_12, cd_dd), max(cd_12, cd_dd)]
    return _pchip_eval(xs, ys, mach)


# -------------------------------------------------------------- configuration
@dataclass
class Configuration:
    """Wing-body-tail jet configuration for drag, area-rule and boom analysis.

    Lengths in m, areas in m^2. The wing's MAC quarter chord sits at
    ``wing_position`` x body length; the horizontal tail's quarter-chord MAC is
    ``tail_arm`` behind it. The inlet's captured stream tube is removed from
    the external area from ``inlet_position`` aft, and the exhaust fills the
    base, so a flow-through body closes at the tail.
    """
    wing_area: float
    aspect_ratio: float = 2.5
    le_sweep_deg: float = 45.0
    taper: float = 0.25
    thickness_ratio: float = 0.04
    body_length: float = 3.0
    body_diameter: float = 0.3
    nose_fineness: float = 3.0
    boattail_fraction: float = 0.25
    htail_area: float = 0.0
    vtail_area: float = 0.0
    tail_arm: float = 1.0
    tail_thickness_ratio: float = 0.04
    inlet_capture_area: float = 0.0
    inlet_position: float = 0.35
    wing_position: float = 0.55
    laminar_fraction: float = 0.0
    roughness: float = SMOOTH_PAINT
    e_wd: float = 1.8
    korn: float = 0.87
    cd_misc: float = 0.0
    suction_supersonic: float = 0.25
    ac_supersonic: float = 0.45
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self):
        for name in ("wing_area", "aspect_ratio", "body_length", "body_diameter",
                     "thickness_ratio", "nose_fineness", "tail_arm"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive.")
        if not 0 <= self.taper <= 1:
            raise ValueError("Taper ratio must be between 0 and 1.")
        if not 0 <= self.le_sweep_deg < 80:
            raise ValueError("Leading-edge sweep must be between 0 and 80 deg.")
        if min(self.htail_area, self.vtail_area, self.inlet_capture_area, self.cd_misc) < 0:
            raise ValueError("Tail, inlet and miscellaneous drag inputs must be non-negative.")
        if self.inlet_capture_area >= self.body_frontal_area:
            raise ValueError("Inlet capture area must be smaller than the body cross-section.")
        if not 0.05 <= self.boattail_fraction <= 0.5:
            raise ValueError("Boattail fraction must be between 0.05 and 0.5 of body length.")
        if self.nose_length + self.boattail_fraction * self.body_length >= self.body_length:
            raise ValueError("Body too short for its nose; raise length or reduce nose fineness.")

    # ------------------------------------------------------------- geometry
    @property
    def span(self):
        return math.sqrt(self.wing_area * self.aspect_ratio)

    @property
    def root_chord(self):
        return 2.0 * self.wing_area / (self.span * (1.0 + self.taper))

    @property
    def mac(self):
        lam = self.taper
        return 2.0 / 3.0 * self.root_chord * (1 + lam + lam ** 2) / (1 + lam)

    @property
    def mac_y(self):
        return self.span / 6.0 * (1 + 2 * self.taper) / (1 + self.taper)

    @property
    def body_frontal_area(self):
        return math.pi * self.body_diameter ** 2 / 4.0

    @property
    def nose_length(self):
        return self.nose_fineness * self.body_diameter

    def body_radius(self, x):
        """Tangent-ogive nose, cylinder, and a boattail closing to the nozzle exit."""
        r = 0.5 * self.body_diameter
        if x <= 0 or x >= self.body_length:
            return 0.0 if x <= 0 else self._base_radius
        if x < self.nose_length:
            rho = (r ** 2 + self.nose_length ** 2) / (2 * r)
            return math.sqrt(max(rho ** 2 - (self.nose_length - x) ** 2, 0.0)) + r - rho
        tail_start = self.body_length * (1.0 - self.boattail_fraction)
        if x > tail_start:
            f = (x - tail_start) / (self.body_length - tail_start)
            return r + (self._base_radius - r) * 0.5 * (1 - math.cos(math.pi * f))
        return r

    @property
    def _base_radius(self):
        return math.sqrt(self.inlet_capture_area / math.pi)

    @staticmethod
    def _planform(area, aspect, sweep, taper, x_quarter_mac, single=False):
        """Straight-tapered surface. ``single`` is a vertical fin: aspect = height^2/area."""
        extent = math.sqrt(area * aspect)
        semi = extent if single else extent / 2.0
        root = 2.0 * area / (extent * (1 + taper))
        mac = 2.0 / 3.0 * root * (1 + taper + taper ** 2) / (1 + taper)
        y_mac = semi / 3.0 * (1 + 2 * taper) / (1 + taper)
        tan_le = math.tan(math.radians(sweep))
        x_le_root = x_quarter_mac - 0.25 * mac - y_mac * tan_le
        return {"semi": semi, "root": root, "taper": taper, "tan_le": tan_le,
                "x_le_root": x_le_root, "mac": mac}

    @property
    def wing_geometry(self):
        return self._planform(self.wing_area, self.aspect_ratio, self.le_sweep_deg,
                              self.taper, self.wing_position * self.body_length)

    def tail_geometries(self):
        x_tail = self.wing_position * self.body_length + self.tail_arm
        out = []
        if self.htail_area > 0:
            out.append(self._planform(self.htail_area, 3.0, max(self.le_sweep_deg, 30.0), 0.35, x_tail))
        if self.vtail_area > 0:
            out.append(self._planform(self.vtail_area, 1.4, max(self.le_sweep_deg, 40.0), 0.35,
                                      x_tail, single=True))
        return out

    @staticmethod
    def _surface_area_at(x, g, thickness_ratio, y_start):
        """Cross-sectional area of a biconvex surface cut normal to the axis at x."""
        semi, strips, total = g["semi"], 24, 0.0
        if semi <= y_start:
            return 0.0
        dy = (semi - y_start) / strips
        for i in range(strips):
            y = y_start + (i + 0.5) * dy
            chord = g["root"] * (1 - (1 - g["taper"]) * y / semi)
            xi = (x - g["x_le_root"] - y * g["tan_le"]) / chord
            if 0 < xi < 1:
                total += 4 * thickness_ratio * chord * xi * (1 - xi) * dy
        return total

    def area_distribution(self, stations=201):
        """External cross-sectional area S(x) at Mach 1 (normal) cuts."""
        key = ("area", stations)
        if key in self._cache:
            return self._cache[key]
        wing = self.wing_geometry
        tails = self.tail_geometries()
        r = 0.5 * self.body_diameter
        extent = [0.0, self.body_length]
        for g in [wing] + tails:
            tip_le = g["x_le_root"] + g["semi"] * g["tan_le"]
            extent[0] = min(extent[0], g["x_le_root"])
            extent[1] = max(extent[1], tip_le + g["root"] * g["taper"], g["x_le_root"] + g["root"])
        xs = [extent[0] + (extent[1] - extent[0]) * i / (stations - 1) for i in range(stations)]
        x_inlet = self.inlet_position * self.body_length
        areas = []
        for x in xs:
            body = math.pi * self.body_radius(x) ** 2
            if x > self.body_length:
                body = 0.0
            elif x >= x_inlet:
                # The captured stream tube leaves the external flow at the inlet.
                # Fading it in over one diameter avoids a nonphysical area step.
                fade = _smoothstep(x, x_inlet, x_inlet + self.body_diameter)
                body = max(body - fade * self.inlet_capture_area, 0.0)
            area = body + 2 * self._surface_area_at(x, wing, self.thickness_ratio, r)
            for i, g in enumerate(tails):
                single = i == len(tails) - 1 and self.vtail_area > 0
                area += (1 if single else 2) * self._surface_area_at(
                    x, g, self.tail_thickness_ratio, 0.0 if single else r)
            areas.append(area)
        self._cache[key] = (xs, areas)
        return xs, areas

    @property
    def sears_haack(self):
        if "sh" not in self._cache:
            xs, areas = self.area_distribution()
            self._cache["sh"] = area_rule.equivalent_sears_haack(xs, areas)
        return self._cache["sh"]

    def wetted_areas(self):
        wing = self.wing_geometry
        r = 0.5 * self.body_diameter
        exposed = self.wing_area * (1.0 - (2 * r / self.span) * (2 - (1 - self.taper) * 2 * r / self.span)
                                    / (1 + self.taper))
        n = 200
        dx = self.body_length / n
        body = sum(2 * math.pi * self.body_radius((i + 0.5) * dx) * dx for i in range(n))
        surfaces = {"wing": 2.0 * (1 + 0.2 * self.thickness_ratio) * max(exposed, 0.0),
                    "fuselage": body,
                    "horizontal tail": 2.0 * (1 + 0.2 * self.tail_thickness_ratio) * self.htail_area,
                    "vertical tail": 2.0 * (1 + 0.2 * self.tail_thickness_ratio) * self.vtail_area}
        lengths = {"wing": wing["mac"], "fuselage": self.body_length,
                   "horizontal tail": math.sqrt(self.htail_area / 3.0) if self.htail_area else 1.0,
                   "vertical tail": math.sqrt(self.vtail_area / 1.4) if self.vtail_area else 1.0}
        return surfaces, lengths

    # ---------------------------------------------------------- aerodynamics
    def lift_slope(self, mach):
        return wing_lift_slope(mach, self.aspect_ratio, self.le_sweep_deg, self.taper)

    def k_factor(self, mach):
        return induced_drag_factor(mach, self.aspect_ratio, self.le_sweep_deg, self.taper,
                                   self.suction_supersonic)

    def cd0(self, mach, altitude):
        """Zero-lift drag breakdown on the wing reference area."""
        check_mach(mach)
        key = ("cd0", round(mach, 6), round(altitude, 3))
        if key in self._cache:
            return self._cache[key]
        air = atmosphere.at(altitude)
        velocity = max(mach, 0.05) * air.sound_speed
        surfaces, lengths = self.wetted_areas()
        quarter = sweep_at(0.25, self.le_sweep_deg, self.aspect_ratio, self.taper)
        m_dd = self.drag_divergence(quarter)
        blend = _smoothstep(mach, min(m_dd, 0.95), 1.2)  # form factors fade to 1 supersonic
        friction = {}
        for name, wetted in surfaces.items():
            if wetted <= 0:
                continue
            length = lengths[name]
            re = air.density * velocity * length / air.viscosity
            cf = skin_friction(re, mach, length, self.roughness, self.laminar_fraction)
            if name == "fuselage":
                ff = aero.form_factor_body(self.body_length / self.body_diameter)
            else:
                tc = self.thickness_ratio if name == "wing" else self.tail_thickness_ratio
                ff = aero.form_factor_wing(tc, min(mach, m_dd), 0.5, quarter)
            ff = (1 - blend) * ff + blend * 1.0
            friction[name] = cf * ff * wetted / self.wing_area
        sh = self.sears_haack
        wave = wave_drag_coefficient(mach, sh["dq_same_max_area"], self.wing_area,
                                     self.thickness_ratio, quarter, self.le_sweep_deg,
                                     self.e_wd, self.korn, m_dd=m_dd)
        out = {"friction": friction, "friction_total": sum(friction.values()),
               "wave": wave, "misc": self.cd0_misc_at(mach),
               "m_dd": m_dd, "m_cr": critical_mach(m_dd)}
        out["total"] = out["friction_total"] + wave + out["misc"]
        self._cache[key] = out
        return out

    def drag_divergence(self, quarter_sweep_deg=None):
        """Configuration drag-divergence Mach. Korn for the wing, capped at 0.97
        because the body's own drag rise begins below Mach 1 regardless of the wing."""
        if quarter_sweep_deg is None:
            quarter_sweep_deg = sweep_at(0.25, self.le_sweep_deg, self.aspect_ratio, self.taper)
        return min(MDD_CAP, drag_divergence_mach(self.thickness_ratio, 0.0, quarter_sweep_deg, self.korn))

    def cd0_misc_at(self, mach):
        return self.cd_misc

    def drag_coefficient(self, mach, altitude, cl):
        return self.cd0(mach, altitude)["total"] + self.k_factor(mach) * cl ** 2

    def drag(self, mach, altitude, weight, load_factor=1.0):
        """Drag force (N) and CL for level flight at ``load_factor`` g."""
        air = atmosphere.at(altitude)
        q = 0.5 * air.density * (mach * air.sound_speed) ** 2
        cl = load_factor * weight / (q * self.wing_area)
        return q * self.wing_area * self.drag_coefficient(mach, altitude, cl), cl

    def lift_to_drag_max(self, mach, altitude):
        cd0 = self.cd0(mach, altitude)["total"]
        k = self.k_factor(mach)
        return 0.5 / math.sqrt(cd0 * k), math.sqrt(cd0 / k)


# ------------------------------------------------------------------ stability
def longitudinal_stability(configuration, mach, cg_fraction_mac, tail_efficiency=0.9,
                           body_apparent_mass=0.85):
    """Neutral point and static margin, as fractions of MAC from the MAC leading edge.

    Wing: Mach-dependent lift slope and aerodynamic centre. Tail: the same
    methods on a 3:1 tail planform, with downwash 2 CL_alpha / (pi A) from the
    wing's local lift slope. Body: Munk's unstable moment 2 k V / (S c), with k
    the apparent-mass factor, which shifts the neutral point forward.
    """
    c = configuration
    a_w = c.lift_slope(mach)
    g = c.wing_geometry
    mac = g["mac"]
    x_le_mac = c.wing_position * c.body_length - 0.25 * mac
    x_ac_w = aerodynamic_center(mach, c.ac_supersonic)
    terms = a_w * x_ac_w
    total = a_w
    if c.htail_area > 0:
        a_t = wing_lift_slope(mach, 3.0, max(c.le_sweep_deg, 30.0), 0.35)
        downwash = min(0.9, 2 * a_w / (math.pi * c.aspect_ratio))
        effective = tail_efficiency * a_t * (c.htail_area / c.wing_area) * (1 - downwash)
        tail_mac = c._planform(c.htail_area, 3.0, 30.0, 0.35, 0.0)["mac"]
        tail_ac = (c.wing_position * c.body_length + c.tail_arm
                   + (aerodynamic_center(mach, c.ac_supersonic) - 0.25) * tail_mac)
        x_ac_t = (tail_ac - x_le_mac) / mac
        terms += effective * x_ac_t
        total += effective
    from .jet_weights import body_volume
    cm_body = 2 * body_apparent_mass * body_volume(c) / (c.wing_area * mac)
    x_np = (terms - cm_body) / total
    return {"neutral_point": x_np, "static_margin": x_np - cg_fraction_mac,
            "wing_lift_slope": a_w, "wing_ac": x_ac_w, "body_shift": -cm_body / total}


def directional_stability(configuration, mach, tail_efficiency=0.9):
    """C_n_beta per radian: vertical tail minus the body (Raymer eq. 16.47 form)."""
    c = configuration
    from .jet_weights import body_volume
    body = -1.3 * body_volume(c) / (c.wing_area * c.span)
    if c.vtail_area <= 0:
        return {"cn_beta": body, "tail": 0.0, "body": body}
    a_v = wing_lift_slope(mach, 2 * 1.4, max(c.le_sweep_deg, 40.0), 0.35) / 2.0
    tail = tail_efficiency * a_v * c.vtail_area * c.tail_arm / (c.wing_area * c.span)
    return {"cn_beta": tail + body, "tail": tail, "body": body}
