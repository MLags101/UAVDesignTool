"""Jet aircraft point performance, to Mach 2.

Combines :class:`uavlib.supersonic.Configuration` aerodynamics with a
:class:`uavlib.airbreathing.Turbojet` (or engine deck):

* specific excess power Ps = V (T - D) / W over a Mach-altitude grid;
* flight envelope from lift, thrust, dynamic-pressure, temperature and Mach limits;
* minimum-time / minimum-fuel climb by Rutowski's energy method;
* cruise by stepwise Breguet integration with part-power fuel flow;
* sustained turn, takeoff ground roll;
* the Mattingly master equation for thrust-loading constraint diagrams.
"""

import math
from dataclasses import dataclass

from . import atmosphere
from .atmosphere import G
from .supersonic import MACH_LIMIT


@dataclass
class JetAircraft:
    configuration: object
    engine: object
    cl_max: float = 1.0
    max_dynamic_pressure: float = 60000.0
    temperature_limit: float = math.inf
    installed_thrust_factor: float = 1.0
    afterburner_allowed: bool = True

    def air(self, altitude):
        return atmosphere.at(altitude)

    def thrust(self, mach, altitude, afterburner=None):
        use = self.afterburner_allowed if afterburner is None else afterburner
        state = self.engine.max_thrust(mach, altitude, use)
        return state["thrust"] * self.installed_thrust_factor, state["fuel_flow"]

    def drag(self, mach, altitude, weight, load_factor=1.0):
        return self.configuration.drag(mach, altitude, weight, load_factor)

    def excess_power(self, mach, altitude, weight, load_factor=1.0, afterburner=None):
        """Ps (m/s) at full thrust."""
        air = self.air(altitude)
        velocity = mach * air.sound_speed
        thrust, _fuel = self.thrust(mach, altitude, afterburner)
        drag, _cl = self.drag(mach, altitude, weight, load_factor)
        return velocity * (thrust - drag) / weight

    def stall_mach(self, altitude, weight):
        air = self.air(altitude)
        v = math.sqrt(2 * weight / (air.density * self.configuration.wing_area * self.cl_max))
        return v / air.sound_speed

    def q_limit_mach(self, altitude):
        air = self.air(altitude)
        return math.sqrt(2 * self.max_dynamic_pressure / air.density) / air.sound_speed

    def temperature_limit_mach(self, altitude):
        if not math.isfinite(self.temperature_limit):
            return math.inf
        t = self.air(altitude).temperature
        ratio = self.temperature_limit / t
        return math.sqrt(max(ratio - 1, 0) / (0.2 * 0.89)) if ratio > 1 else 0.0

    def thrust_limits(self, altitude, weight, afterburner=None, step=0.02):
        """Mach ranges where level flight is possible on thrust (Ps >= 0)."""
        machs = [0.1 + step * i for i in range(int((MACH_LIMIT - 0.1) / step) + 1)]
        ok = []
        for m in machs:
            try:
                ok.append(self.excess_power(m, altitude, weight, 1.0, afterburner) >= 0)
            except ValueError:
                ok.append(False)
        bands, start = [], None
        for m, good in zip(machs, ok):
            if good and start is None:
                start = m
            if not good and start is not None:
                bands.append((start, m - step))
                start = None
        if start is not None:
            bands.append((start, machs[-1]))
        return bands

    def envelope_at(self, altitude, weight, afterburner=None):
        """Lowest and highest Mach at one altitude and what limits each."""
        bands = self.thrust_limits(altitude, weight, afterburner)
        if not bands:
            return None
        low = max(bands[0][0], self.stall_mach(altitude, weight))
        thrust_cap = bands[-1][1] if bands[-1][1] < MACH_LIMIT - 1e-9 else math.inf
        caps = {"thrust": thrust_cap, "dynamic pressure": self.q_limit_mach(altitude),
                "skin temperature": self.temperature_limit_mach(altitude),
                f"Mach {MACH_LIMIT:g} model ceiling": MACH_LIMIT}
        limiter = min(caps, key=caps.get)
        high = caps[limiter]
        if high < low:
            return None
        return {"altitude": altitude, "min_mach": low, "max_mach": high, "limited_by": limiter,
                "transonic_gap": len(bands) > 1,
                "low_limited_by": "stall" if low > bands[0][0] else "thrust"}

    # -------------------------------------------------------------- climb
    def energy_climb(self, weight, final_altitude, final_mach, start_altitude=0.0,
                     start_mach=0.3, objective="time", afterburner=None, step_he=250.0):
        """Rutowski climb: at each energy height pick the altitude that maximises
        Ps (minimum time) or Ps / fuel flow (minimum fuel)."""
        def energy(h, m):
            return h + (m * self.air(h).sound_speed) ** 2 / (2 * G)

        he0, he1 = energy(start_altitude, start_mach), energy(final_altitude, final_mach)
        if he1 <= he0:
            raise ValueError("Final energy height must exceed the start.")
        path, time, fuel, distance = [], 0.0, 0.0, 0.0
        he = he0
        while he < he1 - 1e-6:
            best = None
            for k in range(41):
                h = min(he, final_altitude * 1.05 + 500) * k / 40
                v2 = 2 * G * (he - h)
                if v2 <= 0:
                    continue
                m = math.sqrt(v2) / self.air(h).sound_speed
                if m > MACH_LIMIT or m < self.stall_mach(h, weight) * 1.1:
                    continue
                try:
                    ps = self.excess_power(m, h, weight, 1.0, afterburner)
                    _t, ff = self.thrust(m, h, afterburner)
                except ValueError:
                    continue
                score = ps if objective == "time" else ps / max(ff, 1e-9)
                if ps > 0 and (best is None or score > best[0]):
                    best = (score, h, m, ps, ff)
            if best is None:
                raise ValueError(f"No positive excess power at energy height {he:.0f} m; "
                                 "the target is outside the aircraft's reach.")
            _s, h, m, ps, ff = best
            dhe = min(step_he, he1 - he)
            dt = dhe / ps
            time += dt
            fuel += ff * dt
            distance += m * self.air(h).sound_speed * dt
            path.append({"energy_height": he, "altitude": h, "mach": m, "ps": ps, "time": time})
            he += dhe
        return {"time": time, "fuel": fuel, "distance": distance, "path": path}

    # ------------------------------------------------------------- cruise
    def cruise_fuel_flow(self, mach, altitude, weight, afterburner=None):
        drag, cl = self.drag(mach, altitude, weight)
        allow = self.afterburner_allowed if afterburner is None else afterburner
        state = self.engine.thrust_for(drag / self.installed_thrust_factor, mach, altitude, allow)
        if state is None:
            return None, drag, cl
        return state["fuel_flow"], drag, cl

    def specific_range(self, mach, altitude, weight, afterburner=None):
        """Distance per kg of fuel, m/kg (None if thrust is insufficient)."""
        flow, _drag, _cl = self.cruise_fuel_flow(mach, altitude, weight, afterburner)
        if flow is None or flow <= 0:
            return None
        return mach * self.air(altitude).sound_speed / flow

    def cruise(self, mach, altitude, weight, fuel, steps=20, afterburner=None):
        """Range (m) and time (s) burning ``fuel`` kg at constant Mach and altitude."""
        distance = time = 0.0
        mass = weight / G
        dm = fuel / steps
        velocity = mach * self.air(altitude).sound_speed
        for _ in range(steps):
            flow, _d, _cl = self.cruise_fuel_flow(mach, altitude, (mass - dm / 2) * G, afterburner)
            if flow is None:
                raise ValueError(f"Thrust is insufficient to cruise at Mach {mach:.2f}, {altitude:.0f} m.")
            dt = dm / flow
            time += dt
            distance += velocity * dt
            mass -= dm
        return {"range": distance, "time": time}

    def sustained_load_factor(self, mach, altitude, weight, afterburner=None):
        air = self.air(altitude)
        q = 0.5 * air.density * (mach * air.sound_speed) ** 2
        s = self.configuration.wing_area
        thrust, _ = self.thrust(mach, altitude, afterburner)
        cd0 = self.configuration.cd0(mach, altitude)["total"]
        k = self.configuration.k_factor(mach)
        excess = thrust / (q * s) - cd0
        if excess <= 0:
            return 0.0, "thrust"
        n_thrust = q * s / weight * math.sqrt(excess / k)
        n_lift = q * s * self.cl_max / weight
        return (n_thrust, "thrust") if n_thrust <= n_lift else (n_lift, "lift")

    def takeoff_roll(self, weight, altitude=0.0, friction=0.04, cl_ground=0.1,
                     rotation_factor=1.2, afterburner=None):
        """Ground roll to lift-off at rotation_factor x stall speed, by time stepping."""
        air = self.air(altitude)
        s = self.configuration.wing_area
        v_lof = rotation_factor * math.sqrt(2 * weight / (air.density * s * self.cl_max))
        mass = weight / G
        v = distance = time = 0.0
        dt = 0.02
        while v < v_lof:
            m = v / air.sound_speed
            thrust, _ = self.thrust(m, altitude, afterburner)
            q = 0.5 * air.density * v * v
            cd = self.configuration.cd0(max(m, 0.05), altitude)["total"] + \
                self.configuration.k_factor(max(m, 0.05)) * cl_ground ** 2
            accel = (thrust - q * s * cd - friction * max(weight - q * s * cl_ground, 0)) / mass
            if accel <= 0:
                raise ValueError("Thrust cannot overcome drag and rolling friction before lift-off.")
            v += accel * dt
            distance += v * dt
            time += dt
            if time > 600:
                raise ValueError("Takeoff roll did not converge.")
        return {"distance": distance, "liftoff_speed": v_lof, "time": time}


# --------------------------------------------------- constraint analysis
def thrust_loading(wing_loading, configuration, engine, mach, altitude, load_factor=1.0,
                   excess_power=0.0, weight_fraction=1.0, afterburner=False):
    """Mattingly master equation: sea-level static thrust per takeoff weight."""
    air = atmosphere.at(altitude)
    velocity = mach * air.sound_speed
    q = 0.5 * air.density * velocity ** 2
    alpha = engine.lapse(mach, altitude, afterburner)
    if alpha <= 0:
        return math.inf
    cd0 = configuration.cd0(mach, altitude)["total"]
    k = configuration.k_factor(mach)
    b, n, ws = weight_fraction, load_factor, wing_loading
    drag_term = q / (b * ws) * (k * (n * b * ws / q) ** 2 + cd0)
    return b / alpha * (drag_term + excess_power / velocity)


def takeoff_thrust_loading(wing_loading, engine, cl_max, ground_roll, altitude=0.0,
                           rotation_factor=1.2, friction=0.04):
    """Mattingly takeoff constraint (drag neglected, average friction added)."""
    air = atmosphere.at(altitude)
    alpha = engine.lapse(0.0, altitude, False)
    return (rotation_factor ** 2 * wing_loading / (air.density * G * cl_max * ground_roll)
            + friction) / alpha


def landing_wing_loading(cl_max, landing_speed, altitude=0.0, weight_fraction=1.0,
                         approach_factor=1.3):
    """Largest takeoff wing loading meeting an approach-speed limit."""
    air = atmosphere.at(altitude)
    v_stall = landing_speed / approach_factor
    return 0.5 * air.density * v_stall ** 2 * cl_max / weight_fraction
