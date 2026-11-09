"""Small supersonic jet UAV model, family ``supersonic`` (Mach 0-2).

Requirements workflow: the mission is flown with the configuration's
Mach-dependent drag and a turbojet cycle; engine sea-level static thrust is
sized by the most demanding mission point (cruise thrust, or climb and
acceleration with the minimum excess power), fuel by the mission burn, and the
takeoff mass by a physical build-up -- all closed together.

Hardware workflow: a supplied ``jet_engine`` (cycle parameters or a measured
deck) and fuel tanks are flown as installed, with margins on thrust and fuel.

Mission segment kinds: takeoff, launch, climb, accelerate, cruise, descent.
"""
import math

from uavlib import airbreathing, compressible, jet_weights, sonic_boom
from uavlib import supersonic as aero
from uavlib.atmosphere import at as isa
from .schema import EvaluationResult
from .templates import PARAMETERS, METRICS
from .vehicles import register_model, positive

G = 9.80665
SEGMENT_KINDS = ("takeoff", "launch", "climb", "accelerate", "cruise", "descent")
PROPULSIONS = ("turbojet", "afterburning_turbojet")
_TECHNOLOGY_FIELDS = set(jet_weights.Technology.__dataclass_fields__)


class _Propulsion:
    """Engine maps normalised to sea-level static thrust and cached per condition.

    The cycle is scale-free -- thrust and fuel flow are proportional to the
    engine's size -- so one map serves every iteration of the sizing loop.
    """

    def __init__(self, engine, scale, afterburner, maps=None):
        self.engine, self.scale, self.afterburner = engine, scale, afterburner
        self._maps = {} if maps is None else maps

    def _map(self, mach, altitude):
        key = (round(mach, 5), round(altitude, 2))
        if key in self._maps:
            return self._maps[key]
        e = self.engine
        if isinstance(e, airbreathing.EngineDeck):
            top = e.max_thrust(mach, altitude)
            points, dry = [(top["thrust"], top["fuel_flow"])], 0
            if top["thrust"] <= 0:
                raise ValueError(f"Engine deck gives no thrust at Mach {mach:.2f}, {altitude:.0f} m")
        else:
            top = e.control_tt4(mach, altitude)
            points = []
            for f in (0.55, 0.7, 0.85, 0.95, 1.0):
                try:
                    s = e.point(mach, altitude, tt4=f * top)
                except ValueError:
                    continue
                if s["thrust"] > 0 and (not points or s["thrust"] > points[-1][0]):
                    points.append((s["thrust"], s["fuel_flow"]))
            if not points:
                raise ValueError(f"Engine produces no thrust at Mach {mach:.2f}, {altitude:.0f} m")
            dry = len(points) - 1
            if self.afterburner and e.afterburner:
                tt5 = top * e._tau_t
                for f in (0.3, 0.6, 1.0):
                    s = e.point(mach, altitude, tt7=tt5 + f * (e.tt7_max - tt5))
                    if s["thrust"] > points[-1][0]:
                        points.append((s["thrust"], s["fuel_flow"]))
        self._maps[key] = (points, dry)
        return points, dry

    def maximum(self, mach, altitude, afterburner=True):
        points, dry = self._map(mach, altitude)
        thrust, fuel = points[-1] if afterburner else points[dry]
        return thrust * self.scale, fuel * self.scale

    def unit_maximum(self, mach, altitude, afterburner=True):
        points, dry = self._map(mach, altitude)
        return (points[-1] if afterburner else points[dry])[0]

    def fuel_for(self, required, mach, altitude, afterburner=True):
        """Fuel flow for a thrust, or None if it exceeds what is available."""
        points, dry = self._map(mach, altitude)
        usable = points if afterburner else points[:dry + 1]
        r = required / self.scale
        if r > usable[-1][0] * (1 + 1e-9):
            return None
        if r <= usable[0][0]:
            return usable[0][1] * r / usable[0][0] * self.scale   # TSFC held below the map
        for (t0, f0), (t1, f1) in zip(usable, usable[1:]):
            if r <= t1:
                return (f0 + (f1 - f0) * (r - t0) / (t1 - t0)) * self.scale
        return usable[-1][1] * self.scale


def _segment_mach(segment, altitude, fallback):
    if segment.mach is not None:
        return segment.mach
    if segment.speed > 0:
        return segment.speed / isa(altitude).sound_speed
    return fallback


class JetModel:
    parameters = PARAMETERS
    metrics = METRICS

    @staticmethod
    def fixed_sizing(sized):
        """Quantities a robustness/uncertainty scenario must hold at their sized values."""
        return {"_fixed_thrust": sized.metrics["installed_thrust"],
                "_fixed_fuel": sized.metrics["fuel_capacity"]}

    # ---------------------------------------------------------------- setup
    def _configuration(self, p, a, capture):
        return aero.Configuration(
            wing_area=p["wing_area"], aspect_ratio=p["aspect_ratio"], le_sweep_deg=p["le_sweep"],
            taper=p["taper"], thickness_ratio=p["thickness_ratio"], body_length=p["body_length"],
            body_diameter=p["body_diameter"], nose_fineness=a["nose_fineness"],
            boattail_fraction=a["boattail_fraction"], htail_area=p["tail_area"],
            vtail_area=p["vtail_area"], tail_arm=p["tail_arm"], inlet_capture_area=capture,
            inlet_position=a["inlet_position"], wing_position=a["wing_position"],
            laminar_fraction=a["laminar_fraction"], e_wd=a["e_wd"], korn=a["korn"],
            cd_misc=a["cd_misc"], suction_supersonic=a["suction_supersonic"],
            ac_supersonic=a["ac_supersonic"])

    def _engine(self, study, p, a, afterburner):
        """Engine model, fixed SLS thrust, installed mass, afterburner flag and deck scale.

        Cycle engines are built at 1 N so their maps scale with the sized thrust;
        a deck is absolute per engine and scales with the engine count.
        """
        engines = [c for c in study.vehicle.components if c.kind == "jet_engine"]
        if study.workflow == "hardware" and not engines:
            raise ValueError("Fixed-hardware jet study needs a jet_engine component")
        if len(engines) > 1:
            raise ValueError("Use one jet_engine record; its quantity counts identical engines")
        cycle = dict(pressure_ratio=p["pressure_ratio"], tt4_max=p["turbine_temperature"],
                     throttle_ratio=a["throttle_ratio"], tt7_max=a["tt7_max"], e_c=a["e_c"],
                     e_t=a["e_t"], eta_b=a["eta_b"], subsonic_recovery=a["subsonic_recovery"],
                     inlet="ramp" if a["inlet_ramps"] >= 1 else "pitot",
                     inlet_ramps=max(1, int(a["inlet_ramps"])),
                     nozzle="ideal" if a["nozzle_ideal"] >= 0.5 else "convergent")
        if engines:
            c = engines[0]
            props = c.properties
            ab = bool(props.get("afterburner", afterburner))
            if "deck" in props:
                deck = airbreathing.EngineDeck(rows=props["deck"], afterburner=ab)
                return deck, deck.sls_thrust * c.quantity, c.mass * c.quantity, ab, float(c.quantity)
            if "sls_thrust" not in props:
                raise ValueError("jet_engine needs sls_thrust (N) and cycle values, or a deck")
            for key, prop in (("pressure_ratio", "pressure_ratio"), ("tt4_max", "turbine_temperature"),
                              ("tt7_max", "tt7_max")):
                if prop in props:
                    cycle[key] = float(props[prop])
            engine = airbreathing.Turbojet(sls_thrust=1.0, afterburner=ab, **cycle)
            return engine, float(props["sls_thrust"]) * c.quantity, c.mass * c.quantity, ab, None
        engine = airbreathing.Turbojet(sls_thrust=1.0, afterburner=afterburner, **cycle)
        return engine, None, None, afterburner, None

    # -------------------------------------------------------------- mission
    def _fly(self, study, p, a, config, prop, mass, afterburner):
        """Fly the mission once. Returns totals, per-point rows and sizing demands."""
        reserve_ps = a["min_excess_power"]
        climb_ab = afterburner and a["climb_afterburner"] >= 0.5
        cruise_ab = afterburner and a["cruise_afterburner"] >= 0.5
        h = study.mission.segments[0].altitude
        mach = 0.0
        start_mass, overburn = mass, None
        time = distance = fuel = 0.0
        rows, demand, notes = [], 0.0, []
        thrust_margin, ps_margin = math.inf, math.inf
        segment_times = {}
        takeoff_distance = None
        max_q = max_temp = max_mach = 0.0
        min_transonic_ps = math.inf
        cruise_points = []

        def record(segment, m, alt, thrust, drag, flow, ps, ab):
            nonlocal max_q, max_temp, max_mach
            air = isa(alt)
            q = 0.5 * air.density * (m * air.sound_speed) ** 2
            max_q = max(max_q, q)
            max_mach = max(max_mach, m)
            max_temp = max(max_temp, compressible.recovery_temperature(air.temperature, m))
            rows.append({"segment": segment.name, "time": time, "distance": distance, "mach": m,
                         "altitude": alt, "speed": m * air.sound_speed, "mass": mass,
                         "thrust": thrust, "drag": drag, "fuel_flow": flow, "fuel_used": fuel,
                         "ps": ps, "dynamic_pressure": q, "afterburner": bool(ab)})

        for segment in study.mission.segments:
            start = time
            if segment.kind == "launch":
                h = segment.altitude
                mach = _segment_mach(segment, h, 0.3)
                record(segment, mach, h, 0.0, 0.0, 0.0, 0.0, False)
            elif segment.kind == "takeoff":
                h = segment.altitude
                air = isa(h)
                weight = mass * G
                v_lof = 1.2 * math.sqrt(2 * weight / (air.density * config.wing_area * a["cl_max"]))
                m_lof = v_lof / air.sound_speed
                t0, f0 = prop.maximum(0.0, h, False)
                t1, f1 = prop.maximum(min(m_lof, 0.6), h, False)
                demand = max(demand, 1.25 * a["runway_friction"] * weight / prop.unit_maximum(0.0, h, False))
                cd = config.cd0(0.1, h)["total"] + config.k_factor(0.1) * 0.1 ** 2
                v, roll, dt, t_roll = 0.0, 0.0, 0.05, 0.0
                while v < v_lof:
                    thrust = t0 + (t1 - t0) * min(v / v_lof, 1.0)
                    q = 0.5 * air.density * v * v
                    accel = (thrust - q * config.wing_area * cd
                             - a["runway_friction"] * max(weight - q * config.wing_area * 0.1, 0)) / mass
                    if accel <= 0.05:
                        accel = 0.05     # keeps the sizing loop alive; margin records the shortfall
                        thrust_margin = min(thrust_margin, -1.0)
                    v += accel * dt
                    roll += v * dt
                    t_roll += dt
                    if t_roll > 300:
                        break
                takeoff_distance = roll
                burn = 0.5 * (f0 + f1) * (t_roll + segment.duration)
                fuel += burn
                mass -= burn
                time += t_roll + segment.duration
                distance += roll
                mach = m_lof
                record(segment, mach, h, t1, 0.0, f1, 0.0, False)
            elif segment.kind in ("climb", "accelerate"):
                if segment.kind == "climb":
                    h1 = segment.end_altitude if segment.end_altitude is not None else p["cruise_altitude"]
                    m1 = segment.end_mach if segment.end_mach is not None else (
                        segment.end_speed / isa(h1).sound_speed if segment.end_speed else mach)
                else:
                    h1 = h
                    m1 = segment.end_mach if segment.end_mach is not None else (
                        segment.end_speed / isa(h).sound_speed if segment.end_speed else p["cruise_mach"])
                if m1 > aero.MACH_LIMIT + 1e-9:
                    raise ValueError(f"Segment {segment.name} exceeds the Mach 2 ceiling")
                h0, m0 = h, max(mach, 0.25)
                steps = 12

                def energy(alt, m):
                    return alt + (m * isa(alt).sound_speed) ** 2 / (2 * G)

                if energy(h1, m1) <= energy(h0, m0):
                    raise ValueError(f"Segment {segment.name} must gain energy; use descent to slow or descend")
                for k in range(steps):
                    ha, ma = h0 + (h1 - h0) * k / steps, m0 + (m1 - m0) * k / steps
                    hb, mb = h0 + (h1 - h0) * (k + 1) / steps, m0 + (m1 - m0) * (k + 1) / steps
                    hm, mm = 0.5 * (ha + hb), 0.5 * (ma + mb)
                    weight = mass * G
                    drag, _cl = config.drag(mm, hm, weight)
                    thrust, flow = prop.maximum(mm, hm, climb_ab)
                    velocity = mm * isa(hm).sound_speed
                    ps = velocity * (thrust - drag) / weight
                    need = drag + weight * reserve_ps / velocity
                    demand = max(demand, need / prop.unit_maximum(mm, hm, climb_ab))
                    ps_margin = min(ps_margin, ps / reserve_ps - 1)
                    if 0.95 <= mm <= 1.2:
                        min_transonic_ps = min(min_transonic_ps, ps)
                    # Below the required excess power the segment cannot be flown as
                    # specified; time and fuel are taken at the minimum and the negative
                    # excess-power margin marks the design infeasible.
                    dt = (energy(hb, mb) - energy(ha, ma)) / max(ps, reserve_ps)
                    burn = flow * dt
                    fuel += burn
                    mass -= burn
                    time += dt
                    distance += velocity * dt
                    record(segment, mm, hm, thrust, drag, flow, ps, climb_ab)
                h, mach = h1, m1
            elif segment.kind == "cruise":
                if segment.mach is None and segment.speed <= 0:
                    m, alt = p["cruise_mach"], p["cruise_altitude"]
                else:
                    alt = segment.altitude if segment.altitude > 0 else h
                    m = _segment_mach(segment, alt, mach)
                if alt > h + 500 or m > mach + 0.1:   # slowing or descending needs no model
                    notes.append(f"{segment.name} starts at Mach {m:.2f}, {alt:.0f} m without a "
                                 f"climb/accelerate segment from Mach {mach:.2f}, {h:.0f} m")
                aero.check_mach(m)
                steps = 6
                dt = segment.duration / steps
                velocity = m * isa(alt).sound_speed
                for _ in range(steps):
                    weight = mass * G
                    drag, cl = config.drag(m, alt, weight)
                    demand = max(demand, drag / prop.unit_maximum(m, alt, cruise_ab))
                    available, _ = prop.maximum(m, alt, cruise_ab)
                    thrust_margin = min(thrust_margin, (available - drag) / available)
                    flow = prop.fuel_for(drag, m, alt, cruise_ab)
                    if flow is None:     # short of thrust: burn at the maximum and let margins report it
                        flow = prop.maximum(m, alt, cruise_ab)[1] * drag / available
                    ab_on = drag > prop.maximum(m, alt, False)[0]
                    burn = flow * dt
                    fuel += burn
                    mass -= burn
                    time += dt
                    distance += velocity * dt
                    record(segment, m, alt, drag, drag, flow, 0.0, ab_on)
                    cruise_points.append((m, alt, weight, cl, drag))
                h, mach = alt, m
            elif segment.kind == "descent":
                h1 = segment.end_altitude if segment.end_altitude is not None else 0.0
                m = _segment_mach(segment, h, mach)
                hm = 0.5 * (h + h1)
                _t, flow = prop.maximum(min(m, 0.9), hm, False)
                burn = a["idle_fuel_fraction"] * flow * segment.duration
                velocity = m * isa(hm).sound_speed
                fuel += burn
                mass -= burn
                time += segment.duration
                distance += velocity * segment.duration
                record(segment, m, hm, 0.0, 0.0, a["idle_fuel_fraction"] * flow, 0.0, False)
                h, mach = h1, m
            else:
                raise ValueError(f"Supersonic missions use segment kinds {', '.join(SEGMENT_KINDS)}")
            segment_times[segment.name] = time - start
            if mass < 0.05 * start_mass:
                # Only possible mid-sizing or with grossly short hardware; flagged, not fatal,
                # so the closure loop can recover. The final mission must not overburn.
                mass, overburn = 0.05 * start_mass, segment.name
        return {"overburn": overburn, "fuel": fuel, "time": time, "distance": distance, "rows": rows, "demand": demand,
                "thrust_margin": thrust_margin, "ps_margin": ps_margin, "segment_times": segment_times,
                "takeoff_distance": takeoff_distance, "max_q": max_q, "max_temp": max_temp,
                "max_mach": max_mach, "transonic_ps": min_transonic_ps, "cruise_points": cruise_points,
                "notes": notes, "end_mass": mass}

    # ------------------------------------------------------------- evaluate
    def evaluate(self, study, p):
        a = study.vehicle.assumptions
        if study.vehicle.propulsion not in PROPULSIONS:
            raise ValueError("Supersonic family propulsion must be turbojet or afterburning_turbojet")
        afterburner = study.vehicle.propulsion == "afterburning_turbojet"
        hardware = study.workflow == "hardware"
        positive(p, "wing_area", "aspect_ratio", "thickness_ratio", "body_length", "body_diameter",
                 "tail_arm", "cruise_mach", "pressure_ratio", "turbine_temperature")
        if p["payload"] < 0:
            raise ValueError("Payload cannot be negative")
        if p["cruise_mach"] > aero.MACH_LIMIT:
            raise ValueError("Cruise Mach is above the Mach 2 model ceiling")
        if not study.mission.segments:
            raise ValueError("Supersonic mission needs at least one segment")
        for s in study.mission.segments:
            if s.kind not in SEGMENT_KINDS:
                raise ValueError(f"Segment kind {s.kind} is not a jet kind ({', '.join(SEGMENT_KINDS)})")
        positive(a, "max_q", "skin_temperature_limit", "max_static_margin", "min_excess_power", "cl_max", "max_mass",
                 "closure_tolerance", "fuel_density", "engine_thrust_to_weight", "load_factor")
        tech = jet_weights.Technology(**{k: v for k, v in a.items() if k in _TECHNOLOGY_FIELDS})
        reserve = study.mission.reserve_fraction
        engine, fixed_thrust, engine_mass, afterburner, deck_scale = self._engine(study, p, a, afterburner)
        tanks = [c for c in study.vehicle.components if c.kind == "tank"]
        others = [c for c in study.vehicle.components if c.kind not in ("jet_engine", "tank", "wing")]
        fixed_fuel = None
        if tanks:
            fixed_fuel = sum(float(c.properties["fuel_mass"]) * c.quantity for c in tanks)
        elif hardware:
            fixed_fuel = p["fuel_mass"]
        if "_fixed_thrust" in p:
            fixed_thrust, fixed_fuel = p["_fixed_thrust"], p["_fixed_fuel"]
        if hardware and fixed_thrust is None:
            fixed_thrust = p["installed_thrust"]
        sizing = fixed_thrust is None

        design_flow = (engine.max_thrust(p["cruise_mach"], p["cruise_altitude"], False)["mass_flow"]
                       if deck_scale is None else None)
        wing_hw = next((c for c in study.vehicle.components if c.kind == "wing"), None)
        if wing_hw is not None:
            p["wing_area"] = float(wing_hw.properties.get("area", p["wing_area"]))
            p["aspect_ratio"] = float(wing_hw.properties.get("aspect_ratio", p["aspect_ratio"]))

        def scale(thrust):
            return thrust if deck_scale is None else deck_scale

        def capture_for(thrust):
            if design_flow is None:
                return float(next((c.properties.get("capture_area") for c in study.vehicle.components
                                   if c.kind == "jet_engine"), 0.0) or 0.0)
            return airbreathing.capture_area(design_flow * thrust, p["cruise_mach"], p["cruise_altitude"])

        def masses(config, mass, thrust, fuel_capacity):
            breakdown, notes = jet_weights.build_up(config, tech, mass, thrust, afterburner, p["payload"],
                                                    fuel_capacity, a["load_factor"], p.get("structure_margin", 1.0))
            if engine_mass is not None:
                breakdown["engine"] = engine_mass
                breakdown["installation"] = engine_mass * tech.installation_fraction
            if tanks:
                breakdown["fuel system"] = sum(c.mass * c.quantity for c in tanks)
            if wing_hw is not None:
                breakdown["wing"] = wing_hw.mass * wing_hw.quantity
            if others:
                breakdown["supplied components"] = sum(c.mass * c.quantity for c in others)
            return breakdown, notes

        mass = max(20.0, 4 * p["payload"] + 30.0)
        thrust = fixed_thrust or 0.9 * mass * G
        fuel_capacity = fixed_fuel if fixed_fuel is not None else 0.3 * mass
        config = self._configuration(p, a, capture_for(thrust))
        converged, residual = False, math.inf
        maps = {}   # normalised engine maps are size-independent: share them across iterations
        for _ in range(120):
            prop = _Propulsion(engine, scale(thrust), afterburner, maps)
            sim = self._fly(study, p, a, config, prop, mass, afterburner)
            new_thrust = sim["demand"] * p.get("thrust_margin", 1.0) if sizing else thrust
            new_fuel = (sim["fuel"] / (1 - reserve) * p.get("storage_margin", 1.0)
                        if fixed_fuel is None else fixed_fuel)
            breakdown, spar = masses(config, mass, new_thrust, new_fuel)
            new_mass = sum(breakdown.values())
            if not math.isfinite(new_mass) or new_mass > a["max_mass"]:
                raise ValueError("Mass closure diverged beyond the max_mass technology limit")
            residual = max(abs(new_mass - mass) / mass, abs(new_thrust - thrust) / max(thrust, 1.0),
                           abs(new_fuel - fuel_capacity) / max(fuel_capacity, 1e-3))
            mass += 0.7 * (new_mass - mass)
            thrust += 0.7 * (new_thrust - thrust)
            fuel_capacity += 0.7 * (new_fuel - fuel_capacity)
            capture = capture_for(thrust)
            if abs(capture - config.inlet_capture_area) > 0.01 * max(capture, 1e-6):
                config = self._configuration(p, a, capture)
            if residual < a["closure_tolerance"]:
                converged = True
                break
        config = self._configuration(p, a, capture_for(thrust))
        prop = _Propulsion(engine, scale(thrust), afterburner, maps)
        sim = self._fly(study, p, a, config, prop, mass, afterburner)
        breakdown, spar = masses(config, mass, thrust, fuel_capacity)
        mass = sum(breakdown.values())
        return self._result(study, p, a, config, prop, sim, mass, thrust, fuel_capacity, breakdown,
                            spar, tech, reserve, converged, residual, afterburner)

    # --------------------------------------------------------------- result
    def _result(self, study, p, a, config, prop, sim, mass, thrust, fuel_capacity, breakdown, spar,
                tech, reserve, converged, residual, afterburner):
        weight = mass * G
        cruise_air = isa(p["cruise_altitude"])
        cm, ch = p["cruise_mach"], p["cruise_altitude"]
        drag, cl = config.drag(cm, ch, weight)
        ld = weight / drag
        volume = jet_weights.fuel_volume_available(config, tech) * tech.fuel_density
        landing_mass = max(sim["end_mass"], 0.05 * mass)
        sea = isa(0.0)
        stall = math.sqrt(2 * landing_mass * G / (sea.density * config.wing_area * a["cl_max"]))

        # Highest level-flight Mach at the cruise altitude, full afterburner.
        def ps(m):
            t, _f = prop.maximum(m, ch, afterburner)
            d, _ = config.drag(m, ch, weight)
            return t - d
        max_mach = 0.0
        for i in range(31):
            m = min(0.5 + 0.05 * i, aero.MACH_LIMIT)
            if ps(m) >= 0:
                max_mach = m
        if 0 < max_mach < aero.MACH_LIMIT:
            lo, hi = max_mach, min(max_mach + 0.05, aero.MACH_LIMIT)
            for _ in range(12):
                mid = 0.5 * (lo + hi)
                lo, hi = (mid, hi) if ps(mid) >= 0 else (lo, mid)
            max_mach = lo

        transonic = sim["transonic_ps"]
        if not math.isfinite(transonic):
            v = 1.1 * cruise_air.sound_speed
            t, _f = prop.maximum(1.1, ch, afterburner)
            transonic = v * (t - config.drag(1.1, ch, weight)[0]) / weight

        q = 0.5 * cruise_air.density * (cm * cruise_air.sound_speed) ** 2
        cd0 = config.cd0(cm, ch)["total"]
        k = config.k_factor(cm)
        available, _ = prop.maximum(cm, ch, afterburner)
        excess = available / (q * config.wing_area) - cd0
        load = q * config.wing_area / weight * math.sqrt(excess / k) if excess > 0 else 0.0
        load = min(load, q * config.wing_area * a["cl_max"] / weight)

        subsonic = aero.longitudinal_stability(config, 0.6, p["cg_position"])
        supersonic_sm = aero.longitudinal_stability(config, max(cm, 1.2), p["cg_position"])
        top = max(sim["max_mach"], cm)
        cn_beta = aero.directional_stability(config, min(top, aero.MACH_LIMIT))["cn_beta"] * math.pi / 180
        boom = 0.0
        supersonic_points = [pt for pt in sim["cruise_points"] if pt[0] > 1.0]
        if supersonic_points:
            m_b, h_b, w_b, _cl, _d = max(supersonic_points, key=lambda pt: pt[0])
            boom = sonic_boom.aircraft_boom(config, w_b, m_b, h_b, a["boom_reflection"])["overpressure"]

        climb_time = sum(t for s, t in sim["segment_times"].items()
                         if any(seg.name == s and seg.kind == "climb" for seg in study.mission.segments))
        accel_time = sum(t for s, t in sim["segment_times"].items()
                         if any(seg.name == s and seg.kind == "accelerate" for seg in study.mission.segments))
        metrics = dict(
            takeoff_mass=mass, payload=p["payload"], fuel_used=sim["fuel"], fuel_capacity=fuel_capacity,
            installed_thrust=thrust, thrust_to_weight=thrust / weight,
            wing_loading=weight / config.wing_area, range=sim["distance"], mission_time=sim["time"],
            endurance=sim["time"], cruise_speed=cm * cruise_air.sound_speed, cruise_mach=cm,
            max_mach=max_mach, supersonic_lift_to_drag=ld,
            wave_drag_coefficient=config.cd0(cm, ch)["wave"], stall_speed=stall,
            landing_speed=1.3 * stall, static_margin=subsonic["static_margin"],
            static_margin_supersonic=supersonic_sm["static_margin"], directional_stability=cn_beta,
            max_skin_temperature=sim["max_temp"], sonic_boom_overpressure=boom,
            transonic_excess_power=transonic, fuel_volume_margin=volume / fuel_capacity - 1,
            sustained_load_factor=load, time_to_climb=climb_time, acceleration_time=accel_time,
            max_dynamic_pressure=sim["max_q"], mass_closure=residual * mass,
            structural_margin=p.get("structure_margin", 1.0) - 1.0)
        if sim["takeoff_distance"] is not None:
            metrics["takeoff_distance"] = sim["takeoff_distance"]
        margins = dict(
            fuel=(fuel_capacity * (1 - reserve) - sim["fuel"]) / fuel_capacity,
            fuel_volume=metrics["fuel_volume_margin"],
            thrust=min(sim["thrust_margin"], 1.0) if math.isfinite(sim["thrust_margin"]) else 1.0,
            excess_power=min(sim["ps_margin"], 1.0) if math.isfinite(sim["ps_margin"]) else 1.0,
            dynamic_pressure=1 - sim["max_q"] / a["max_q"],
            skin_temperature=(a["skin_temperature_limit"] - sim["max_temp"]) / a["skin_temperature_limit"],
            static_margin=subsonic["static_margin"] - a["min_static_margin"],
            # An excessive supersonic margin costs trim drag and pitch authority (not modelled).
            supersonic_static_margin=a["max_static_margin"] - supersonic_sm["static_margin"],
            directional_stability=cn_beta / 0.0005)
        warnings = ["Conceptual supersonic model: linear-theory aerodynamics, parametric turbojet "
                    "cycle and physical mass build-up; calibrate technology assumptions.",
                    "Mach 0.9-1.2 aerodynamics are faired between subsonic and supersonic methods."]
        warnings += sim["notes"]
        if sim["overburn"]:
            margins["fuel"] = min(margins["fuel"], -1.0)
            warnings.append(f"The aircraft cannot complete the mission: fuel burn by {sim['overburn']} "
                            "exceeds its mass (thrust is far short of drag). Results past that point are "
                            "not physical.")
        if not converged:
            warnings.append("Thrust/fuel/mass closure did not reach the tolerance.")
        design = dict(p)
        design.update(installed_thrust=thrust, fuel_mass=fuel_capacity,
                      _inlet_capture_area=config.inlet_capture_area)
        return EvaluationResult(design=design, metrics=metrics, margins=margins,
                                mass_breakdown=breakdown, mission_history=sim["rows"],
                                warnings=warnings, valid=True, converged=converged,
                                closure_residual=residual)


register_model("supersonic", JetModel())
