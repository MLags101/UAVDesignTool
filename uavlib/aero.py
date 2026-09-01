"""Aerodynamic relations for fixed-wing aircraft.

Everything here is classical thin-airfoil / lifting-line theory at the level of
fidelity appropriate to conceptual and preliminary design. Where a viscous
correction is conventional, it is applied and noted.
"""

import math

from . import atmosphere as atm
from .atmosphere import G

TWO_PI = 2.0 * math.pi


def dynamic_pressure(velocity: float, altitude: float = 0.0) -> float:
    """q = 1/2 rho V^2, Pa."""
    return 0.5 * atm.density(altitude) * velocity ** 2


# ------------------------------------------------------------------ lift
def lift_curve_slope_3d(aspect_ratio: float, a0: float = TWO_PI,
                        oswald: float = 0.95, sweep_qc_deg: float = 0.0) -> float:
    """Finite-wing lift-curve slope, per radian.

    Prandtl lifting-line: a = a0 / (1 + a0/(pi*e*AR)). A 2D section slope of
    2*pi is the thin-airfoil value; real sections run a little lower. Sweep
    reduces the effective slope by cos(sweep).
    """
    if aspect_ratio <= 0:
        raise ValueError("Aspect ratio must be greater than zero.")
    a0_eff = a0 * math.cos(math.radians(sweep_qc_deg))
    return a0_eff / (1.0 + a0_eff / (math.pi * oswald * aspect_ratio))


def cl_max_3d(cl_max_2d: float, sweep_qc_deg: float = 0.0) -> float:
    """3D maximum lift coefficient from a 2D section value.

    A finite wing does not reach its section Clmax: the usual conceptual-design
    figure is about 0.9 of the 2D value, reduced further by sweep.
    """
    return 0.9 * cl_max_2d * math.cos(math.radians(sweep_qc_deg))


def stall_speed(mass: float, wing_area: float, cl_max: float,
                altitude: float = 0.0, load_factor: float = 1.0) -> float:
    """Stall speed, m/s. In a turn the stall speed rises with sqrt(n)."""
    rho = atm.density(altitude)
    if wing_area <= 0 or cl_max <= 0:
        raise ValueError("Wing area and CLmax must be greater than zero.")
    return math.sqrt(2.0 * mass * G * load_factor / (rho * wing_area * cl_max))


def cl_required(mass: float, wing_area: float, velocity: float,
                altitude: float = 0.0, load_factor: float = 1.0) -> float:
    """Lift coefficient needed to hold level flight at a given speed."""
    q = dynamic_pressure(velocity, altitude)
    if q <= 0 or wing_area <= 0:
        raise ValueError("Velocity and wing area must be greater than zero.")
    return mass * G * load_factor / (q * wing_area)


# ------------------------------------------------------------------ drag
def oswald_efficiency(aspect_ratio: float, sweep_qc_deg: float = 0.0) -> float:
    """Estimated Oswald span efficiency factor.

    Raymer's straight-wing correlation, with the swept-wing form used past 30
    degrees. Typical RC values land between 0.75 and 0.85.

    The correlation was fitted around transport aspect ratios (6-10) and grows
    increasingly conservative above AR 12 -- a well-built tapered sailplane wing
    achieves 0.85-0.95 where this returns closer to 0.6. Override the estimate
    when a better figure is known; :func:`oswald_note` flags the affected range.
    """
    if aspect_ratio <= 0:
        raise ValueError("Aspect ratio must be greater than zero.")
    if sweep_qc_deg <= 30.0:
        e = 1.78 * (1.0 - 0.045 * aspect_ratio ** 0.68) - 0.64
    else:
        e = 4.61 * (1.0 - 0.045 * aspect_ratio ** 0.68) \
            * math.cos(math.radians(sweep_qc_deg)) ** 0.15 - 3.1
    return max(0.5, min(e, 1.0))


def oswald_note(aspect_ratio: float) -> str:
    """Caveat for the Oswald estimate, empty when the correlation is reliable."""
    if aspect_ratio > 12.0:
        return ("Oswald estimate is conservative above AR 12; a well-built "
                "tapered wing may reach 0.85-0.95. Override if known.")
    return ""


def induced_drag_factor(aspect_ratio: float, oswald: float) -> float:
    """k in CD = CD0 + k*CL^2."""
    if aspect_ratio <= 0 or oswald <= 0:
        raise ValueError("Aspect ratio and Oswald factor must be positive.")
    return 1.0 / (math.pi * oswald * aspect_ratio)


def skin_friction_coefficient(reynolds: float, laminar_fraction: float = 0.0) -> float:
    """Flat-plate skin friction coefficient.

    Blended between the laminar Blasius result and the turbulent
    Prandtl-Schlichting correlation. Small models can hold a lot of laminar
    run, so ``laminar_fraction`` matters more here than at full scale.
    """
    re = max(reynolds, 1.0)
    cf_lam = 1.328 / math.sqrt(re)
    cf_turb = 0.455 / (math.log10(re) ** 2.58)
    f = max(0.0, min(laminar_fraction, 1.0))
    return f * cf_lam + (1.0 - f) * cf_turb


def form_factor_wing(thickness_ratio: float, mach: float = 0.0,
                     x_c_max: float = 0.3, sweep_max_deg: float = 0.0) -> float:
    """Raymer form factor for a lifting surface."""
    t_c = max(thickness_ratio, 0.01)
    sweep = math.radians(sweep_max_deg)
    return ((1.0 + 0.6 / x_c_max * t_c + 100.0 * t_c ** 4)
            * (1.34 * max(mach, 0.01) ** 0.18 * math.cos(sweep) ** 0.28))


def form_factor_body(fineness_ratio: float) -> float:
    """Raymer form factor for a fuselage or nacelle. f = length / diameter."""
    f = max(fineness_ratio, 1.0)
    return 1.0 + 60.0 / f ** 3 + f / 400.0


def drag_polar(cl: float, cd0: float, k: float) -> float:
    """CD = CD0 + k*CL^2."""
    return cd0 + k * cl * cl


def ld_max(cd0: float, k: float) -> tuple:
    """Best lift-to-drag ratio and the CL at which it occurs.

    L/D peaks where induced drag equals parasite drag.
    """
    if cd0 <= 0 or k <= 0:
        raise ValueError("CD0 and k must be greater than zero.")
    cl_opt = math.sqrt(cd0 / k)
    return 1.0 / (2.0 * math.sqrt(cd0 * k)), cl_opt


def speed_min_drag(mass: float, wing_area: float, cd0: float, k: float,
                   altitude: float = 0.0) -> float:
    """Speed for minimum drag, which is also best glide and best range, m/s."""
    _, cl_opt = ld_max(cd0, k)
    return stall_speed_at_cl(mass, wing_area, cl_opt, altitude)


def speed_min_power(mass: float, wing_area: float, cd0: float, k: float,
                    altitude: float = 0.0) -> float:
    """Speed for minimum power required -- best endurance and min sink, m/s.

    Minimum power occurs at CL = sqrt(3*CD0/k), a factor 3^0.25 (about 0.76)
    below the minimum-drag speed.
    """
    if cd0 <= 0 or k <= 0:
        raise ValueError("CD0 and k must be greater than zero.")
    cl = math.sqrt(3.0 * cd0 / k)
    return stall_speed_at_cl(mass, wing_area, cl, altitude)


def stall_speed_at_cl(mass: float, wing_area: float, cl: float,
                      altitude: float = 0.0) -> float:
    """Speed at which level flight requires exactly this CL, m/s."""
    rho = atm.density(altitude)
    if wing_area <= 0 or cl <= 0:
        raise ValueError("Wing area and CL must be greater than zero.")
    return math.sqrt(2.0 * mass * G / (rho * wing_area * cl))


def power_required(mass: float, wing_area: float, velocity: float,
                   cd0: float, k: float, altitude: float = 0.0) -> float:
    """Aerodynamic power required for level flight, W."""
    cl = cl_required(mass, wing_area, velocity, altitude)
    cd = drag_polar(cl, cd0, k)
    q = dynamic_pressure(velocity, altitude)
    return q * wing_area * cd * velocity


# --------------------------------------------------- control surfaces
def flap_effectiveness(chord_fraction: float, viscous: bool = True) -> float:
    """Glauert flap effectiveness parameter tau, 0-1.

    tau is the fraction of a full angle-of-attack change that deflecting the
    control surface is worth: dCL = a * tau * deflection.

        theta_f = acos(2*cf/c - 1)
        tau     = 1 - (theta_f - sin(theta_f)) / pi

    The inviscid result overpredicts; real surfaces achieve roughly 80% of it,
    which ``viscous`` applies. tau is a fraction and can never exceed 1 -- an
    earlier version of this calculation returned values above 1, which is what
    prompted moving it into the shared library.
    """
    cf_c = max(1e-6, min(float(chord_fraction), 1.0))
    theta_f = math.acos(2.0 * cf_c - 1.0)
    tau = 1.0 - (theta_f - math.sin(theta_f)) / math.pi
    return tau * 0.8 if viscous else tau


def hinge_moment_coefficient(chord_fraction: float, deflection_deg: float,
                             alpha_deg: float = 0.0) -> float:
    """Approximate hinge moment coefficient Ch.

    Uses representative Ch_alpha and Ch_delta values for a plain, unbalanced
    flap; aerodynamic balance or a sealed gap reduces these substantially.
    """
    cf_c = max(1e-6, min(float(chord_fraction), 1.0))
    ch_alpha = -0.10 * math.sqrt(cf_c / 0.25)
    ch_delta = -0.30 * math.sqrt(cf_c / 0.25)
    return ch_alpha * math.radians(alpha_deg) + ch_delta * math.radians(deflection_deg)


def roll_rate(velocity: float, span: float, cl_delta_a: float,
              cl_p: float, deflection_deg: float) -> tuple:
    """Steady-state roll rate from aileron deflection.

    Returns (roll rate rad/s, non-dimensional pb/2V). Roll accelerates until
    the damping moment from Cl_p balances the aileron moment.
    """
    if cl_p >= 0:
        raise ValueError("Roll damping Cl_p must be negative.")
    pb_2v = -cl_delta_a * math.radians(deflection_deg) / cl_p
    p = pb_2v * 2.0 * velocity / span if span > 0 else 0.0
    return p, pb_2v


def roll_damping(lift_slope: float, aspect_ratio: float, taper: float = 1.0) -> float:
    """Roll damping derivative Cl_p, per radian (negative)."""
    return -(lift_slope / 12.0) * (1.0 + 3.0 * taper) / (1.0 + taper)


def aileron_control_power(lift_slope: float, tau: float, span: float,
                          root_chord: float, taper: float,
                          y_inboard: float, y_outboard: float,
                          wing_area: float) -> float:
    """Aileron roll control derivative Cl_delta_a, per radian.

    Integrates the strip contribution c(y)*y between the aileron's inboard and
    outboard stations, which is why both stations are needed rather than a
    single "span position".
    """
    if span <= 0 or wing_area <= 0:
        raise ValueError("Span and wing area must be greater than zero.")
    half_span = span / 2.0
    y1 = max(0.0, min(y_inboard, half_span))
    y2 = max(0.0, min(y_outboard, half_span))
    if y2 <= y1:
        raise ValueError("Outboard station must be beyond the inboard station.")

    # c(y) = c_root * (1 - (1-taper) * y/(b/2)); integrate c(y)*y dy.
    slope = (1.0 - taper) / half_span
    integral = (root_chord * ((y2 ** 2 - y1 ** 2) / 2.0
                              - slope * (y2 ** 3 - y1 ** 3) / 3.0))
    return 2.0 * lift_slope * tau * integral / (wing_area * span)


# ------------------------------------------------- stability geometry
def neutral_point(x_ac_wing: float, mac: float, wing_area: float,
                  a_wing: float, a_tail: float, tail_area: float,
                  tail_arm: float, downwash_slope: float = 0.0,
                  tail_efficiency: float = 0.9) -> float:
    """Stick-fixed neutral point measured from the same datum as ``x_ac_wing``.

    x_np = x_ac + (a_t/a_w) * eta_t * (S_t/S_w) * l_t * (1 - de/dalpha)
    """
    if wing_area <= 0 or a_wing <= 0:
        raise ValueError("Wing area and wing lift slope must be positive.")
    tail_term = ((a_tail / a_wing) * tail_efficiency * (tail_area / wing_area)
                 * tail_arm * (1.0 - downwash_slope))
    return x_ac_wing + tail_term


def downwash_slope(aspect_ratio: float, lift_slope: float = None) -> float:
    """de/dalpha at the tail. The classic low-AR estimate is 2*a/(pi*AR)."""
    if aspect_ratio <= 0:
        raise ValueError("Aspect ratio must be greater than zero.")
    a = lift_slope if lift_slope is not None else lift_curve_slope_3d(aspect_ratio)
    return min(0.9, 2.0 * a / (math.pi * aspect_ratio))


def static_margin(x_cg: float, x_np: float, mac: float) -> float:
    """Static margin as a fraction of MAC. Positive is statically stable."""
    if mac <= 0:
        raise ValueError("MAC must be greater than zero.")
    return (x_np - x_cg) / mac


# Static margin guidance for radio-controlled aircraft.
SM_BANDS = (
    (0.0, "UNSTABLE. The CG is behind the neutral point; the aircraft will "
          "diverge in pitch and is not flyable without active stabilisation."),
    (0.05, "Very marginal. Twitchy and demanding; acceptable only for pylon "
           "racers and 3D aerobatic models flown by experienced pilots."),
    (0.10, "Agile. Suits sport and aerobatic models."),
    (0.20, "Stable. The usual target for sport, FPV and camera platforms."),
    (0.35, "Very stable. Typical of trainers and gliders; expect sluggish "
           "pitch response and a trim drag penalty."),
    (float("inf"), "Excessively stable. Elevator authority will be poor and "
                   "the model may be difficult to flare on landing."),
)


def static_margin_note(sm: float) -> str:
    for threshold, note in SM_BANDS:
        if sm < threshold:
            return note
    return SM_BANDS[-1][1]
