"""Single-stage vertical point-mass trajectory, with explicit event handling."""
import math
from uavlib.structures import buckling_critical_load, tube_properties
from .physics import atmosphere, interpolate
from .schema import EvaluationResult
from .templates import PARAMETERS, METRICS
from .vehicles import register_model, positive


class RocketModel:
    parameters = PARAMETERS
    metrics = METRICS

    def evaluate(self, study, p):
        from scipy.integrate import solve_ivp
        a = study.vehicle.assumptions
        positive(p, "body_length", "body_diameter", "fin_area", "fin_span", "recovery_area")
        positive(a, "skin_areal_mass", "material_density", "allowable_stress", "modulus", "specific_impulse",
                 "max_q", "max_acceleration", "max_landing_speed", "parachute_cd", "rocket_max_mach")
        if p["payload"] < 0:
            raise ValueError("Payload must be nonnegative")
        if a["step"] <= 0 or a["max_time"] <= 0 or a["guide_length"] <= 0:
            raise ValueError("Trajectory step, time limit, and guide length must be positive")
        hardware = study.workflow == "hardware"
        motor = next((c for c in study.vehicle.components if c.kind == "rocket_motor"), None)
        if hardware and motor is None:
            raise ValueError("Fixed-hardware rocket needs a rocket_motor with thrust and propellant mass curves")
        if motor:
            if motor.quantity != 1:
                raise ValueError("Single-stage model requires one aggregate rocket motor")
            thrust_map = motor.properties["thrust_curve"]
            mass_map = motor.properties["propellant_curve"]
            burn = thrust_map[-1][0]
            if thrust_map[0][0] != 0 or mass_map[0][0] != 0 or mass_map[-1][0] != burn:
                raise ValueError("Motor curves must share time domain starting at zero")
            interpolate(thrust_map, 0)
            interpolate(mass_map, 0)
            if any(t[1] < 0 for t in thrust_map) or any(t[1] < 0 for t in mass_map):
                raise ValueError("Motor curves cannot contain negative thrust or mass")
            if any(b[1] > c[1] for c, b in zip(mass_map, mass_map[1:])):
                raise ValueError("Propellant mass must not increase")
            propellant = mass_map[0][1]
            inert_motor = motor.mass
            motor_position = p.get(f"component.{motor.id}.position", motor.position)
        else:
            positive(p, "propellant_mass", "burn_time")
            propellant, burn = p["propellant_mass"], p["burn_time"]
            thrust = propellant * 9.80665 * a["specific_impulse"] / burn
            thrust_map = [[0., thrust], [burn, thrust]]
            mass_map = [[0., propellant], [burn, 0.]]
            inert_motor = propellant * a["motor_inert_fraction"]
            motor_position = .85 * p["body_length"]
        p.update(propellant_mass=propellant, burn_time=burn)
        surface = math.pi * p["body_diameter"] * p["body_length"]
        shell = surface * a["skin_areal_mass"] + 2 * p["fin_area"] * a["skin_areal_mass"]
        recovery_mass = p["recovery_area"] * .08
        other_mass = sum(c.mass * c.quantity for c in study.vehicle.components if c is not motor)
        dry = p["payload"] + shell + inert_motor + recovery_mass + other_mass
        reference_area = math.pi * (p["body_diameter"] / 2) ** 2
        nose_cn = 2.
        fin_cn = 8 * p["fin_area"] / reference_area / (1 + math.sqrt(1 + (2 * p["fin_span"] ** 2 / p["fin_area"]) ** 2))
        cp = (nose_cn * .16 * p["body_length"] + fin_cn * .85 * p["body_length"]) / (nose_cn + fin_cn)
        aero = next((c for c in study.vehicle.components if c.kind == "aerodynamics"), None)
        cd_map = aero.properties.get("cd_mach") if aero else None
        cp_map = aero.properties.get("cp_mach") if aero else None
        if cd_map and not cp_map:
            raise ValueError("Mach-dependent rocket data must include both CD and CP")
        ground = p.get("launch_altitude", 0.)

        def motor_values(t):
            return (interpolate(thrust_map, t), interpolate(mass_map, t)) if t < burn else (0., mass_map[-1][1])

        def properties(t, y, recovery=False):
            h, v = y
            air = atmosphere(ground + max(0., h))
            mach = abs(v) / air.sound_speed
            if not cd_map and mach > a["rocket_max_mach"]:
                raise ValueError("Rocket left subsonic aerodynamic domain; provide CD/CP Mach maps")
            cd = interpolate(cd_map, mach) if cd_map else a["rocket_cd"]
            if cd < 0:
                raise ValueError("Rocket drag coefficient cannot be negative")
            centre_pressure = interpolate(cp_map, mach) if cp_map else cp
            thrust, remaining = motor_values(t)
            mass = dry + remaining
            moment = shell * .5 * p["body_length"] + p["payload"] * .2 * p["body_length"]
            moment += (inert_motor + remaining) * motor_position + recovery_mass * .35 * p["body_length"]
            moment += sum(c.mass * c.quantity * p.get(f"component.{c.id}.position", c.position)
                          for c in study.vehicle.components if c is not motor)
            cg = moment / mass
            q = .5 * air.density * v * v
            drag = q * (cd * reference_area + (a["parachute_cd"] * p["recovery_area"] if recovery else 0.))
            gravity = 9.80665 * (6371000 / (6371000 + ground + max(0., h))) ** 2
            acceleration = (thrust - math.copysign(drag, v)) / mass - gravity
            return dict(time=t, altitude=h, speed=v, mass=mass, cg=cg, cp=centre_pressure,
                        static_margin=(centre_pressure - cg) / p["body_diameter"],
                        dynamic_pressure=q, mach=mach, acceleration=acceleration, thrust=thrust)

        ignition = properties(0, [0, 0])
        liftoff = 0.
        if ignition["acceleration"] <= 0:
            from scipy.optimize import brentq
            times = sorted(set([float(row[0]) for row in thrust_map] + [burn * i / 100 for i in range(101)]))
            for lower, upper in zip(times, times[1:]):
                if properties(upper, [0, 0])["acceleration"] > 0:
                    liftoff = brentq(lambda t: properties(t, [0, 0])["acceleration"], lower, upper) + 1e-8
                    break
            else:
                raise ValueError("Motor never produces enough thrust to leave the launch guide")

        def rhs(t, y):
            row = properties(t, y)
            return [y[1], row["acceleration"]]

        def apex(t, y):
            return y[1]
        apex.direction, apex.terminal = -1, True

        def guide(t, y):
            return y[0] - a["guide_length"]
        guide.direction = 1
        ascent = solve_ivp(rhs, (liftoff, a["max_time"]), [0., 1e-9], events=[apex, guide],
                           max_step=a["step"], rtol=1e-7, atol=1e-8)
        if not ascent.success or not len(ascent.t_events[0]):
            raise ValueError("Trajectory did not reach apogee within the time budget")
        if ascent.t[-1] < burn:
            raise ValueError("Apogee before motor burnout is outside recovery model domain")
        apogee = float(ascent.y[0, -1])

        def ground_event(t, y):
            return y[0]
        ground_event.direction, ground_event.terminal = -1, True

        def descending(t, y):
            return [y[1], properties(t, y, True)["acceleration"]]

        descent = solve_ivp(descending, (ascent.t[-1], a["max_time"]), [apogee, 0.],
                            events=ground_event, max_step=max(a["step"], .5), rtol=1e-7, atol=1e-8)
        if not descent.success or not len(descent.t_events[0]):
            raise ValueError("Recovery did not reach ground within the time budget")
        rows = [{**properties(float(t), y), "segment": "Ascent"}
                for t, y in zip(ascent.t, ascent.y.T)]
        rows += [{**properties(float(t), y, True), "segment": "Recovery"}
                 for t, y in zip(descent.t[1:], descent.y.T[1:])]
        exit_speed = float(ascent.y_events[1][0][1]) if len(ascent.y_events[1]) else 0.
        min_sm = min(r["static_margin"] for r in rows if r["segment"] == "Ascent")
        peak_q = max(r["dynamic_pressure"] for r in rows)
        peak_acc = max(abs(r["acceleration"]) for r in rows)
        landing = abs(float(descent.y[1, -1]))
        # Thin-wall axial stress, plus Euler buckling of the body tube as a
        # fixed-free column. Fin flutter and recovery-opening loads are not included.
        thickness = a["skin_areal_mass"] / a["material_density"]
        if thickness <= 0 or 2 * thickness >= p["body_diameter"]:
            raise ValueError("Skin thickness must be positive and less than the body radius")
        stress = (dry + propellant) * peak_acc / (math.pi * p["body_diameter"] * thickness)
        axial_margin = a["allowable_stress"] / max(stress, 1.) - 1
        compressive = (dry + propellant) * peak_acc
        section = tube_properties(p["body_diameter"], thickness)
        critical = buckling_critical_load(a["modulus"], section["I"], p["body_length"], end_condition=2.)
        buckling_margin = critical / compressive - 1 if compressive > 0 else float("inf")
        metrics = dict(takeoff_mass=dry + propellant, payload=p["payload"], apogee=apogee,
                       max_mach=max(r["mach"] for r in rows), max_dynamic_pressure=peak_q,
                       max_acceleration=peak_acc, guide_exit_speed=exit_speed, landing_speed=landing,
                       static_margin=min_sm, cg=rows[0]["cg"], structural_margin=min(axial_margin, buckling_margin))
        margins = dict(stability=min_sm - 1., guide=exit_speed / 12 - 1,
                       dynamic_pressure=1 - peak_q / a["max_q"], acceleration=1 - peak_acc / a["max_acceleration"],
                       recovery=1 - landing / a["max_landing_speed"], structure=metrics["structural_margin"])
        return EvaluationResult(design=p, metrics=metrics, margins=margins,
                                mass_breakdown=dict(payload=p["payload"], airframe=shell,
                                                    motor=inert_motor, propellant=propellant,
                                                    recovery=recovery_mass, other=other_mass),
                                mission_history=rows, valid=True, converged=True,
                                warnings=["Vertical point-mass trajectory; wind, attitude, fin flutter and parachute opening loads unverified.",
                                          "Airframe check is thin-wall axial stress and fixed-free Euler buckling of the body tube.",
                                          "Subsonic CP/drag are preliminary approximations unless supplied Mach maps are used."])


register_model("rocket", RocketModel())
