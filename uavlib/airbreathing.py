"""Turbojet performance and supersonic inlets, to Mach 2.

Engine model
------------
Single-spool turbojet with optional afterburner, following the parametric
cycle and off-design performance analysis in Mattingly, *Elements of
Propulsion* (chapters 7-8): constant turbine temperature and pressure ratios
(choked turbine and nozzle throat), compressor operating line from the work
balance, and the mass flow from the choked turbine inlet. Component losses use
polytropic efficiencies. The engine is defined by its design compressor
pressure ratio and maximum turbine inlet temperature, and scaled to the
sea-level static thrust you specify.

Engine control: below the throttle-ratio break (theta0 <= TR) the compressor is
at its pressure-ratio limit and Tt4 is reduced with inlet temperature; above
it Tt4 sits at its maximum and the compressor unloads. TR = 1 puts the break
at sea-level static standard day; supersonic engines often use 1.05-1.15 to
hold thrust at high Mach.

Inlets
------
MIL-E-5007D recovery, normal-shock (pitot) recovery, and external-compression
ramps (oblique shocks plus a terminal normal shock), including the
Oswatitsch equal-strength optimum.
"""

import math
from dataclasses import dataclass
from functools import lru_cache

from . import atmosphere, compressible

T_STD, P_STD = 288.15, 101325.0
CP_C, GAMMA_C = 1004.0, 1.4
CP_T, GAMMA_T = 1239.0, 1.3
R_C = CP_C * (GAMMA_C - 1) / GAMMA_C
R_T = CP_T * (GAMMA_T - 1) / GAMMA_T
FUEL_HEATING_VALUE = 42.8e6   # J/kg, kerosene
MACH_LIMIT = 2.0


# -------------------------------------------------------------------- inlets
def mil_spec_recovery(mach):
    """MIL-E-5007D ram recovery: 1 subsonic, 1 - 0.075 (M - 1)^1.35 above."""
    return 1.0 if mach <= 1.0 else 1.0 - 0.075 * (mach - 1.0) ** 1.35


def pitot_recovery(mach):
    """Total-pressure recovery of a normal-shock (pitot) inlet."""
    return 1.0 if mach <= 1.0 else compressible.normal_shock(mach)["p02/p01"]


def external_compression(mach, ramp_angles_deg):
    """Recovery of external-compression ramps followed by a terminal normal shock."""
    shocks, recovery, m = [], 1.0, mach
    for angle in ramp_angles_deg:
        if m <= 1.0:
            raise ValueError("Flow is already subsonic before the last ramp; reduce ramp angles.")
        shock = compressible.oblique_shock(m, math.radians(angle))
        recovery *= shock["p02/p01"]
        shocks.append({"deflection_deg": angle, "shock_angle_deg": shock["beta_deg"],
                       "mach_after": shock["M2"], "recovery": shock["p02/p01"]})
        m = shock["M2"]
    terminal = pitot_recovery(m)
    recovery *= terminal
    return {"recovery": recovery, "shocks": shocks, "terminal_mach": m,
            "terminal_recovery": terminal}


def optimum_ramps(mach, ramps):
    """Oswatitsch optimum: every shock (including the terminal one) equally strong."""
    if ramps < 1:
        return external_compression(mach, [])

    def final_mach(normal):
        m, angles = mach, []
        for _ in range(ramps):
            if normal > m:
                return None, angles
            shock = compressible.oblique_shock_from_normal_mach(m, normal)
            angles.append(math.degrees(shock["theta"]))
            m = shock["M2"]
        return m, angles

    lo, hi = 1.0 + 1e-9, mach
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        m, _angles = final_mach(mid)
        if m is None or m < mid:
            hi = mid
        else:
            lo = mid
    _m, angles = final_mach(lo)
    result = external_compression(mach, angles)
    result["ramp_angles_deg"] = angles
    return result


@lru_cache(maxsize=4096)
def _ramp_recovery(mach, ramps):
    return optimum_ramps(mach, ramps)["recovery"]


def inlet_recovery(mach, kind="mil", ramps=1, subsonic_recovery=0.97):
    """Total recovery: subsonic duct loss times the supersonic shock-system recovery."""
    if kind == "mil":
        shock = mil_spec_recovery(mach)
    elif kind == "pitot":
        shock = pitot_recovery(mach)
    elif kind == "ramp":
        # Cached on Mach to 1e-5: the shock-system solve is the costly part of a cycle point.
        shock = _ramp_recovery(round(mach, 5), int(ramps)) if mach > 1 else 1.0
    else:
        raise ValueError("Inlet kind must be mil, pitot or ramp.")
    return subsonic_recovery * shock


def capture_area(mass_flow, mach, altitude):
    """Free-stream tube area that carries the engine's mass flow."""
    air = atmosphere.at(altitude)
    return mass_flow / (air.density * max(mach, 0.05) * air.sound_speed)


# -------------------------------------------------------------------- engine
@dataclass
class Turbojet:
    """Fixed-geometry single-spool turbojet scaled to ``sls_thrust`` (N, dry)."""
    sls_thrust: float = 1000.0
    pressure_ratio: float = 4.0
    tt4_max: float = 1150.0
    throttle_ratio: float = 1.0
    afterburner: bool = False
    tt7_max: float = 1800.0
    e_c: float = 0.80
    e_t: float = 0.85
    eta_b: float = 0.95
    pi_b: float = 0.95
    eta_m: float = 0.97
    pi_n: float = 0.97
    eta_ab: float = 0.90
    pi_ab: float = 0.94
    inlet: str = "mil"
    inlet_ramps: int = 1
    subsonic_recovery: float = 0.97
    nozzle: str = "convergent"     # or "ideal" (fully expanded C-D nozzle)

    def __post_init__(self):
        if self.sls_thrust <= 0:
            raise ValueError("Sea-level static thrust must be positive.")
        if not 1.5 <= self.pressure_ratio <= 40:
            raise ValueError("Compressor pressure ratio must be between 1.5 and 40.")
        if not 800 <= self.tt4_max <= 2000:
            raise ValueError("Turbine inlet temperature must be between 800 and 2000 K.")
        if not 0.9 <= self.throttle_ratio <= 1.3:
            raise ValueError("Throttle ratio must be between 0.9 and 1.3.")
        if self.afterburner and not self.tt4_max < self.tt7_max <= 2400:
            raise ValueError("Afterburner temperature must exceed Tt4 and be at most 2400 K.")
        for name in ("e_c", "e_t", "eta_b", "pi_b", "eta_m", "pi_n", "eta_ab", "pi_ab",
                     "subsonic_recovery"):
            if not 0.5 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0.5 and 1.")
        if self.nozzle not in ("convergent", "ideal"):
            raise ValueError("Nozzle must be convergent or ideal.")
        self._reference()
        self._mass_flow_ref = 1.0
        self._mass_flow_ref = self.sls_thrust / self.point(0.0, 0.0)["thrust"]

    # Reference (design) point: static, theta0 = TR, Tt4 = max, pi_c = design.
    def _reference(self):
        t0 = T_STD * self.throttle_ratio
        self._ref = {"t0": t0, "p0": P_STD, "tau_r": 1.0, "pi_r": 1.0,
                     "pi_d": self.subsonic_recovery, "tt4": self.tt4_max}
        tau_c = self.pressure_ratio ** ((GAMMA_C - 1) / (GAMMA_C * self.e_c))
        self._eta_c = (self.pressure_ratio ** ((GAMMA_C - 1) / GAMMA_C) - 1) / (tau_c - 1)
        tau_lambda = CP_T * self.tt4_max / (CP_C * t0)
        f = (tau_lambda - tau_c) / (self.eta_b * FUEL_HEATING_VALUE / (CP_C * t0) - tau_lambda)
        self._tau_t = 1 - (tau_c - 1) / (self.eta_m * (1 + f) * tau_lambda)
        if self._tau_t <= 0.3:
            raise ValueError("Turbine cannot drive this compressor at this Tt4.")
        self._pi_t = self._tau_t ** (GAMMA_T / ((GAMMA_T - 1) * self.e_t))
        self._ref.update(tau_c=tau_c, pi_c=self.pressure_ratio, tau_lambda=tau_lambda)

    def control_tt4(self, mach, altitude):
        """Maximum Tt4 the control schedule allows at this flight condition."""
        air = atmosphere.at(altitude)
        theta0 = air.temperature * (1 + 0.5 * (GAMMA_C - 1) * mach ** 2) / T_STD
        return self.tt4_max * min(1.0, theta0 / self.throttle_ratio)

    def point(self, mach, altitude, tt4=None, tt7=None):
        """Thrust (N), fuel flow (kg/s) and cycle state at one operating point.

        ``tt4`` defaults to the control maximum. ``tt7`` (afterburner exit) is
        only used with an afterburner; None means dry.
        """
        if not 0 <= mach <= MACH_LIMIT + 1e-9:
            raise ValueError(f"Engine model is limited to Mach 0-{MACH_LIMIT:g}.")
        air = atmosphere.at(altitude)
        t0, p0 = air.temperature, air.pressure
        a0 = math.sqrt(GAMMA_C * R_C * t0)
        ref = self._ref
        tt4 = self.control_tt4(mach, altitude) if tt4 is None else tt4
        tau_r = 1 + 0.5 * (GAMMA_C - 1) * mach ** 2
        pi_r = tau_r ** (GAMMA_C / (GAMMA_C - 1))
        pi_d = inlet_recovery(mach, self.inlet, self.inlet_ramps, self.subsonic_recovery)
        tau_lambda = CP_T * tt4 / (CP_C * t0)
        tau_c = 1 + (ref["tau_c"] - 1) * (tau_lambda / tau_r) / (ref["tau_lambda"] / ref["tau_r"])
        pi_c = (1 + self._eta_c * (tau_c - 1)) ** (GAMMA_C / (GAMMA_C - 1))
        heat = self.eta_b * FUEL_HEATING_VALUE / (CP_C * t0)
        f = (tau_lambda - tau_r * tau_c) / (heat - tau_lambda)
        if f <= 0:
            raise ValueError("Turbine inlet temperature is below compressor exit temperature.")
        mass_flow = self._mass_flow_ref * (p0 * pi_r * pi_d * pi_c) / (
            ref["p0"] * ref["pi_r"] * ref["pi_d"] * ref["pi_c"]) * math.sqrt(ref["tt4"] / tt4)
        tt9_t0 = tau_lambda * self._tau_t * CP_C / CP_T
        pi_ab, f_ab = 1.0, 0.0
        if tt7 is not None and self.afterburner:
            tt5 = tt4 * self._tau_t
            if not tt5 <= tt7 <= self.tt7_max + 1e-9:
                raise ValueError("Afterburner temperature outside the dry-to-maximum range.")
            tau_lambda_ab = CP_T * tt7 / (CP_C * t0)
            f_ab = (1 + f) * (tau_lambda_ab - tau_lambda * self._tau_t) / (
                self.eta_ab * FUEL_HEATING_VALUE / (CP_C * t0) - tau_lambda_ab)
            tt9_t0 = tau_lambda_ab * CP_C / CP_T
            pi_ab = self.pi_ab
        pt9_p0 = pi_r * pi_d * pi_c * self.pi_b * self._pi_t * pi_ab * self.pi_n
        critical = ((GAMMA_T + 1) / 2) ** (GAMMA_T / (GAMMA_T - 1))
        if self.nozzle == "convergent" and pt9_p0 > critical:
            pt9_p9 = critical
        else:
            pt9_p9 = max(pt9_p0, 1.0)
        p0_p9 = pt9_p9 / pt9_p0
        m9 = math.sqrt(2 / (GAMMA_T - 1) * (pt9_p9 ** ((GAMMA_T - 1) / GAMMA_T) - 1))
        t9_t0 = tt9_t0 / pt9_p9 ** ((GAMMA_T - 1) / GAMMA_T)
        v9_a0 = m9 * math.sqrt(GAMMA_T * R_T * t9_t0 / (GAMMA_C * R_C))
        total_f = f + f_ab
        specific = a0 * ((1 + total_f) * v9_a0 - mach
                         + (1 + total_f) * R_T * t9_t0 / (R_C * v9_a0 if v9_a0 > 0 else 1e-9)
                         * (1 - p0_p9) / GAMMA_C)
        thrust = mass_flow * specific
        fuel = mass_flow * total_f
        return {"thrust": thrust, "fuel_flow": fuel,
                "tsfc": fuel / thrust if thrust > 0 else math.inf,
                "specific_thrust": specific, "mass_flow": mass_flow, "pi_c": pi_c,
                "tt4": tt4, "tt7": tt7, "inlet_recovery": pi_d, "exit_mach": m9,
                "fuel_air_ratio": total_f}

    def max_thrust(self, mach, altitude, afterburner=None):
        use_ab = self.afterburner if afterburner is None else (afterburner and self.afterburner)
        return self.point(mach, altitude, tt7=self.tt7_max if use_ab else None)

    def thrust_for(self, required, mach, altitude, allow_afterburner=True):
        """Fuel flow to deliver ``required`` thrust, throttling Tt4 then the afterburner.

        Returns None if the thrust is not available. Below the modelled throttle
        floor (half the control Tt4) the floor TSFC is applied to the lower thrust.
        """
        dry = self.point(mach, altitude)
        if required <= dry["thrust"]:
            top = dry["tt4"]
            floor_tt4 = 0.5 * top
            try:
                floor = self.point(mach, altitude, tt4=floor_tt4)
            except ValueError:
                floor = None
            if floor is None or required <= floor["thrust"]:
                base = floor if floor and floor["thrust"] > 0 else dry
                return {**base, "thrust": required, "fuel_flow": base["tsfc"] * required,
                        "part_power_floor": True}
            lo, hi = floor_tt4, top
            for _ in range(50):
                mid = 0.5 * (lo + hi)
                if self.point(mach, altitude, tt4=mid)["thrust"] < required:
                    lo = mid
                else:
                    hi = mid
            state = self.point(mach, altitude, tt4=hi)
            return {**state, "fuel_flow": state["fuel_flow"] * required / state["thrust"],
                    "thrust": required}
        if not (allow_afterburner and self.afterburner):
            return None
        wet = self.point(mach, altitude, tt7=self.tt7_max)
        if required > wet["thrust"]:
            return None
        lo, hi = dry["tt4"] * self._tau_t, self.tt7_max
        for _ in range(50):
            mid = 0.5 * (lo + hi)
            if self.point(mach, altitude, tt7=mid)["thrust"] < required:
                lo = mid
            else:
                hi = mid
        state = self.point(mach, altitude, tt7=hi)
        return {**state, "fuel_flow": state["fuel_flow"] * required / state["thrust"],
                "thrust": required}

    def lapse(self, mach, altitude, afterburner=None):
        """Maximum thrust divided by sea-level static dry thrust."""
        return self.max_thrust(mach, altitude, afterburner)["thrust"] / self.sls_thrust


@dataclass
class EngineDeck:
    """Measured or manufacturer engine table: rows of mach, altitude, max_thrust, tsfc.

    Part-power fuel flow uses the tabulated TSFC (constant with throttle), which
    is the usual first approximation; it is reported as such.
    """
    rows: list
    sls_thrust: float = 0.0
    afterburner: bool = False

    def __post_init__(self):
        from .optimization.physics import interpolate_grid
        self._lookup = interpolate_grid
        for row in self.rows:
            if row["max_thrust"] < 0 or row["tsfc"] <= 0:
                raise ValueError("Deck thrust must be non-negative and TSFC positive.")
        if not self.sls_thrust:
            self.sls_thrust = self._value(0.0, 0.0, "max_thrust")

    def _value(self, mach, altitude, column):
        return self._lookup(self.rows, ("mach", mach), ("altitude", altitude), column)

    def max_thrust(self, mach, altitude, afterburner=None):
        thrust = self._value(mach, altitude, "max_thrust")
        tsfc = self._value(mach, altitude, "tsfc")
        return {"thrust": thrust, "fuel_flow": thrust * tsfc, "tsfc": tsfc}

    def thrust_for(self, required, mach, altitude, allow_afterburner=True):
        top = self.max_thrust(mach, altitude)
        if required > top["thrust"]:
            return None
        return {"thrust": required, "fuel_flow": required * top["tsfc"], "tsfc": top["tsfc"]}

    def lapse(self, mach, altitude, afterburner=None):
        return self.max_thrust(mach, altitude)["thrust"] / self.sls_thrust
