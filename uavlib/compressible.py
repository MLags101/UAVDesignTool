"""Compressible gas dynamics for a calorically perfect gas.

Isentropic flow, normal and oblique shocks, Prandtl-Meyer expansions and
Taylor-Maccoll cone flow. These are exact relations (NACA Report 1135), not
correlations, so they hold at any Mach number as long as the gas stays
calorically perfect -- roughly below Mach 5 in air.

All angles are in radians unless a name ends in ``_deg``.
"""

import math

GAMMA = 1.4


def _check_mach(mach, minimum=0.0, name="Mach number"):
    if not math.isfinite(mach) or mach < minimum:
        raise ValueError(f"{name} must be at least {minimum:g} (got {mach:g}).")


def _bisect(fn, lo, hi, tolerance=1e-12, iterations=200):
    """Root of a function that changes sign on [lo, hi]."""
    f_lo = fn(lo)
    if f_lo == 0:
        return lo
    if f_lo * fn(hi) > 0:
        raise ValueError("No root in the requested interval.")
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        f_mid = fn(mid)
        if f_mid == 0 or hi - lo < tolerance:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)


# ------------------------------------------------------------- isentropic
def temperature_ratio(mach, gamma=GAMMA):
    """T/T0."""
    _check_mach(mach)
    return 1.0 / (1.0 + 0.5 * (gamma - 1.0) * mach ** 2)


def pressure_ratio(mach, gamma=GAMMA):
    """p/p0."""
    return temperature_ratio(mach, gamma) ** (gamma / (gamma - 1.0))


def density_ratio(mach, gamma=GAMMA):
    """rho/rho0."""
    return temperature_ratio(mach, gamma) ** (1.0 / (gamma - 1.0))


def area_ratio(mach, gamma=GAMMA):
    """A/A* for isentropic flow."""
    _check_mach(mach, 1e-9)
    g = gamma
    return (1.0 / mach) * ((2.0 / (g + 1.0)) * (1.0 + 0.5 * (g - 1.0) * mach ** 2)) ** (
        (g + 1.0) / (2.0 * (g - 1.0)))


def mach_from_area_ratio(ratio, supersonic=True, gamma=GAMMA):
    """Mach number for a given A/A*, on the chosen branch."""
    if ratio < 1.0:
        raise ValueError("A/A* cannot be less than 1.")
    if ratio == 1.0:
        return 1.0
    if supersonic:
        return _bisect(lambda m: area_ratio(m, gamma) - ratio, 1.0, 50.0)
    return _bisect(lambda m: area_ratio(m, gamma) - ratio, 1e-9, 1.0)


def mach_angle(mach):
    """Mach wave angle mu = asin(1/M), radians."""
    _check_mach(mach, 1.0)
    return math.asin(1.0 / mach)


def isentropic(mach, gamma=GAMMA):
    """Every isentropic ratio at once, for reports."""
    out = {"T/T0": temperature_ratio(mach, gamma), "p/p0": pressure_ratio(mach, gamma),
           "rho/rho0": density_ratio(mach, gamma)}
    if mach > 0:
        out["A/A*"] = area_ratio(mach, gamma)
    if mach >= 1.0:
        out["mu_deg"] = math.degrees(mach_angle(mach))
        out["nu_deg"] = math.degrees(prandtl_meyer(mach, gamma))
    return out


# ------------------------------------------------------------ normal shock
def normal_shock(mach, gamma=GAMMA):
    """Downstream state of a normal shock. Ratios are downstream/upstream."""
    _check_mach(mach, 1.0, "Upstream Mach number for a shock")
    g, m2 = gamma, mach ** 2
    mach_down = math.sqrt((1.0 + 0.5 * (g - 1.0) * m2) / (g * m2 - 0.5 * (g - 1.0)))
    p_ratio = 1.0 + 2.0 * g / (g + 1.0) * (m2 - 1.0)
    rho_ratio = (g + 1.0) * m2 / ((g - 1.0) * m2 + 2.0)
    t_ratio = p_ratio / rho_ratio
    p0_ratio = (rho_ratio ** (g / (g - 1.0))) * ((1.0 / p_ratio) ** (1.0 / (g - 1.0)))
    return {"M2": mach_down, "p2/p1": p_ratio, "rho2/rho1": rho_ratio,
            "T2/T1": t_ratio, "p02/p01": p0_ratio}


# ----------------------------------------------------------- oblique shock
def deflection_angle(mach, beta, gamma=GAMMA):
    """Flow deflection theta for shock angle beta (theta-beta-M relation)."""
    m2s = (mach * math.sin(beta)) ** 2
    numerator = 2.0 / math.tan(beta) * (m2s - 1.0)
    denominator = mach ** 2 * (gamma + math.cos(2.0 * beta)) + 2.0
    return math.atan(numerator / denominator)


def max_deflection_shock_angle(mach, gamma=GAMMA):
    """Shock angle at which the deflection is greatest (detachment point)."""
    _check_mach(mach, 1.0)
    g, m2 = gamma, mach ** 2
    root = math.sqrt((g + 1.0) * ((g + 1.0) * m2 ** 2 / 16.0 + 0.5 * (g - 1.0) * m2 + 1.0))
    sin2 = ((g + 1.0) * m2 / 4.0 - 1.0 + root) / (g * m2)
    return math.asin(math.sqrt(min(1.0, sin2)))


def max_deflection(mach, gamma=GAMMA):
    """Largest wedge angle that keeps the shock attached, radians."""
    return deflection_angle(mach, max_deflection_shock_angle(mach, gamma), gamma)


def shock_angle(mach, theta, strong=False, gamma=GAMMA):
    """Oblique shock angle beta for deflection theta. Raises if detached."""
    _check_mach(mach, 1.0)
    if theta < 0:
        raise ValueError("Deflection angle must be non-negative.")
    mu = mach_angle(mach)
    if theta == 0:
        return math.pi / 2 if strong else mu
    beta_max = max_deflection_shock_angle(mach, gamma)
    theta_max = deflection_angle(mach, beta_max, gamma)
    if theta > theta_max:
        raise ValueError(
            f"Shock detaches: {math.degrees(theta):.2f} deg exceeds the maximum "
            f"{math.degrees(theta_max):.2f} deg deflection at Mach {mach:.3f}.")
    fn = lambda b: deflection_angle(mach, b, gamma) - theta
    if strong:
        return _bisect(fn, beta_max, math.pi / 2)
    return _bisect(fn, mu, beta_max)


def oblique_shock(mach, theta, strong=False, gamma=GAMMA):
    """Downstream state of an oblique shock with flow deflection ``theta``."""
    beta = shock_angle(mach, theta, strong, gamma)
    normal = normal_shock(mach * math.sin(beta), gamma)
    mach_down = normal["M2"] / math.sin(beta - theta)
    return {"beta": beta, "beta_deg": math.degrees(beta), "M2": mach_down,
            "p2/p1": normal["p2/p1"], "rho2/rho1": normal["rho2/rho1"],
            "T2/T1": normal["T2/T1"], "p02/p01": normal["p02/p01"],
            "Mn1": mach * math.sin(beta)}


def oblique_shock_from_normal_mach(mach, normal_mach, gamma=GAMMA):
    """Oblique shock specified by its upstream normal Mach component."""
    if not 1.0 <= normal_mach <= mach:
        raise ValueError("Normal Mach component must lie between 1 and the flight Mach.")
    beta = math.asin(normal_mach / mach)
    theta = deflection_angle(mach, beta, gamma)
    normal = normal_shock(normal_mach, gamma)
    return {"beta": beta, "theta": theta, "M2": normal["M2"] / math.sin(beta - theta),
            "p2/p1": normal["p2/p1"], "T2/T1": normal["T2/T1"], "p02/p01": normal["p02/p01"]}


# -------------------------------------------------------- Prandtl-Meyer
def prandtl_meyer(mach, gamma=GAMMA):
    """Prandtl-Meyer function nu(M), radians."""
    _check_mach(mach, 1.0)
    g = gamma
    a = math.sqrt((g + 1.0) / (g - 1.0))
    s = math.sqrt(mach ** 2 - 1.0)
    return a * math.atan(s / a) - math.atan(s)


def mach_from_prandtl_meyer(nu, gamma=GAMMA):
    """Inverse Prandtl-Meyer function."""
    g = gamma
    nu_max = 0.5 * math.pi * (math.sqrt((g + 1.0) / (g - 1.0)) - 1.0)
    if not 0 <= nu < nu_max:
        raise ValueError("Prandtl-Meyer angle outside the physical range.")
    if nu == 0:
        return 1.0
    return _bisect(lambda m: prandtl_meyer(m, gamma) - nu, 1.0, 1e4)


def expansion(mach, theta, gamma=GAMMA):
    """Isentropic turn of ``theta`` radians away from the flow (expansion fan)."""
    mach_down = mach_from_prandtl_meyer(prandtl_meyer(mach, gamma) + theta, gamma)
    return {"M2": mach_down,
            "p2/p1": pressure_ratio(mach_down, gamma) / pressure_ratio(mach, gamma),
            "T2/T1": temperature_ratio(mach_down, gamma) / temperature_ratio(mach, gamma)}


def turn(mach, theta, gamma=GAMMA):
    """Flow turned by ``theta``: positive compresses (shock), negative expands."""
    if theta > 0:
        return oblique_shock(mach, theta, gamma=gamma)
    if theta < 0:
        return expansion(mach, -theta, gamma)
    return {"M2": mach, "p2/p1": 1.0, "T2/T1": 1.0}


# -------------------------------------------------------------- cone flow
def _taylor_maccoll_cone_angle(mach, beta, gamma, steps=400):
    """Integrate Taylor-Maccoll inward from the shock; return cone angle and Mach."""
    g = gamma
    theta_flow = deflection_angle(mach, beta, gamma)
    shock = oblique_shock_from_normal_mach(mach, mach * math.sin(beta), gamma)
    m2 = shock["M2"]
    v = (2.0 / ((g - 1.0) * m2 ** 2) + 1.0) ** -0.5
    vr, vt = v * math.cos(beta - theta_flow), -v * math.sin(beta - theta_flow)

    def derivative(theta, vr, vt):
        a = 0.5 * (g - 1.0) * (1.0 - vr ** 2 - vt ** 2)
        vtt = (vr * vt ** 2 - a * (2.0 * vr + vt / math.tan(theta))) / (a - vt ** 2)
        return vt, vtt

    h = -beta / steps
    theta = beta
    while vt < 0 and theta > 1e-6:
        k1 = derivative(theta, vr, vt)
        k2 = derivative(theta + h / 2, vr + h / 2 * k1[0], vt + h / 2 * k1[1])
        k3 = derivative(theta + h / 2, vr + h / 2 * k2[0], vt + h / 2 * k2[1])
        k4 = derivative(theta + h, vr + h * k3[0], vt + h * k3[1])
        nvr = vr + h / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0])
        nvt = vt + h / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
        if nvt >= 0:  # interpolate to V_theta = 0, the cone surface
            fraction = vt / (vt - nvt)
            theta += h * fraction
            vr = vr + (nvr - vr) * fraction
            vt = 0.0
            break
        theta, vr, vt = theta + h, nvr, nvt
    surface_mach = math.sqrt(2.0 / (g - 1.0) * vr ** 2 / (1.0 - vr ** 2))
    return theta, surface_mach, shock


def cone_flow(mach, cone_half_angle, gamma=GAMMA):
    """Supersonic flow over a sharp cone at zero incidence (Taylor-Maccoll)."""
    _check_mach(mach, 1.0)
    if not 0 < cone_half_angle < math.radians(60):
        raise ValueError("Cone half-angle must be between 0 and 60 deg.")
    mu = mach_angle(mach)
    beta_hi = max_deflection_shock_angle(mach, gamma)
    fn = lambda b: _taylor_maccoll_cone_angle(mach, b, gamma)[0] - cone_half_angle
    if fn(beta_hi) < 0:
        raise ValueError("Cone shock detaches at this Mach number and half-angle.")
    beta = _bisect(fn, mu + 1e-6, beta_hi, tolerance=1e-10)
    _, surface_mach, shock = _taylor_maccoll_cone_angle(mach, beta, gamma)
    m2 = shock["M2"]
    p_surface = shock["p2/p1"] * pressure_ratio(surface_mach, gamma) / pressure_ratio(m2, gamma)
    cp = (p_surface - 1.0) / (0.5 * gamma * mach ** 2)
    return {"beta": beta, "beta_deg": math.degrees(beta), "surface_mach": surface_mach,
            "pc/p1": p_surface, "cp": cp, "p02/p01": shock["p02/p01"]}


# ---------------------------------------------------------- temperatures
def stagnation_temperature(static_temperature, mach, gamma=GAMMA):
    return static_temperature / temperature_ratio(mach, gamma)


def recovery_temperature(static_temperature, mach, recovery_factor=0.89, gamma=GAMMA):
    """Adiabatic wall temperature. r = Pr^(1/3) ~ 0.89 turbulent, Pr^(1/2) ~ 0.85 laminar."""
    return static_temperature * (1.0 + recovery_factor * 0.5 * (gamma - 1.0) * mach ** 2)
