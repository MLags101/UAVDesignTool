"""Strict-domain conceptual physics used by the workbench."""
import bisect
import math
from uavlib.atmosphere import G, GEOPOTENTIAL_LIMIT, at as isa


def atmosphere(height):
    """USSA layer equations, geopotential metres, 0 to 84852 m (~86 km geometric)."""
    if not 0 <= height <= GEOPOTENTIAL_LIMIT:
        raise ValueError("Atmosphere domain is 0–84852 geopotential metres")
    return isa(height)


def interpolate(points, x):
    """Strict piecewise-linear measured/supplied curve; no extrapolation."""
    if len(points) < 2:
        raise ValueError("A performance map needs at least two points")
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    if any(not math.isfinite(y) for y in xs + ys) or any(b <= a for a, b in zip(xs, xs[1:])):
        raise ValueError("Map coordinates must be finite and strictly increasing")
    if not xs[0] <= x <= xs[-1]:
        raise ValueError(f"Operating point {x:g} outside map [{xs[0]:g}, {xs[-1]:g}]")
    i = min(max(bisect.bisect_right(xs, x) - 1, 0), len(xs) - 2)
    f = (x - xs[i]) / (xs[i + 1] - xs[i])
    return ys[i] + f * (ys[i + 1] - ys[i])


def battery_operating_point(power, voltage, resistance):
    if power < 0 or voltage <= 0 or resistance < 0:
        raise ValueError("Invalid battery operating inputs")
    d = voltage * voltage - 4 * resistance * power
    if d < 0:
        raise ValueError("Battery cannot supply requested power after voltage sag")
    current = 2 * power / (voltage + math.sqrt(d)) if power else 0.0
    return current, voltage - current * resistance


def ideal_hover(thrust, density, area):
    return thrust ** 1.5 / math.sqrt(2 * density * area)


def axial_induced_power(thrust, climb, density, area):
    """Shaft power of an axial climb from momentum theory, outside descent.

    P = T (V_c + v_i) with v_i = -V_c/2 + sqrt((V_c/2)^2 + T/(2 rho A)).
    Negative climb is the vortex-ring regime and is not evaluated here.
    """
    if thrust <= 0 or density <= 0 or area <= 0 or climb < 0:
        raise ValueError("Axial climb power needs positive thrust, density and disk area, and nonnegative climb")
    hover = thrust / (2 * density * area)
    induced = -climb / 2 + math.sqrt((climb / 2) ** 2 + hover)
    return thrust * (climb + induced), induced


def transition_forces(mass, wing_lift, drag, acceleration):
    """Prescribed planar transition: resolve both force components explicitly.

    Positive-only cruise thrust; lift-system resultant carries braking demand.
    The caller must enforce installation/attitude authority for the required tilt.
    """
    if mass <= 0 or not 0 <= wing_lift <= mass * G or drag < 0:
        raise ValueError("Invalid transition force inputs")
    required_x = mass * acceleration + drag
    cruise = max(0., required_x)
    lift_x = min(0., required_x)
    lift_z = mass * G - wing_lift
    return dict(cruise_thrust=cruise, lift_force_x=lift_x, lift_force_z=lift_z,
                lift_thrust=math.hypot(lift_x, lift_z),
                lift_tilt=math.atan2(abs(lift_x), lift_z),
                force_residual_x=cruise + lift_x - drag - mass * acceleration,
                force_residual_z=lift_z + wing_lift - mass * G)


def rotor_performance(thrust, speed, rho, radius, rpm, blades, chord, cd0, lift_slope=5.7,
                      roll_moment=0., pitch_moment=0., axial_speed=0.):
    """Rigid planar rotor: collective/cyclic trim of thrust and two hub moments.

    Uniform inflow, linear section lift, radial cutout 20%, no blade flapping.
    Moments are about disk x (forward) and y (left), normal force along +z.
    This is a steady rotor equilibrium, not a full-aircraft six-DOF trim model.
    """
    omega = rpm * 2 * math.pi / 60
    if min(thrust, rho, radius, omega, chord, blades, lift_slope) <= 0 or blades != int(blades) or speed < 0 or cd0 < 0:
        raise ValueError("Invalid rotor geometry or operating point")
    tip = omega * radius
    if speed / tip > .3:
        raise ValueError("Rotor advance ratio exceeds 0.30 model domain")
    area = math.pi * radius ** 2
    vh = math.sqrt(thrust / (2 * rho * area))
    vi = math.sqrt((math.sqrt(speed ** 4 + 4 * vh ** 4) - speed ** 2) / 2)
    if axial_speed < 0:
        raise ValueError("Negative rotor axial inflow needs a descent/vortex-ring model")
    if axial_speed:
        from scipy.optimize import brentq
        vi = brentq(lambda x: 2 * rho * area * x * math.hypot(speed, axial_speed + x) - thrust,
                    0., vh)
    through_flow = vi + axial_speed
    dr, azimuths = .8 * radius / 20, 24
    import numpy as np
    radii = np.repeat(.2 * radius + (np.arange(20) + .5) * dr, azimuths)
    azimuth = np.tile(2 * math.pi * np.arange(azimuths) / azimuths, 20)
    tangential = omega * radii + speed * np.sin(azimuth)
    if np.any(tangential <= 0):
        raise ValueError("Reverse flow at rotor blade elements is outside the trim model domain")
    phi = np.arctan2(through_flow, tangential)
    q = .5 * rho * (tangential ** 2 + through_flow ** 2) * chord * dr * blades / azimuths
    cos_phi, sin_phi = np.cos(phi), np.sin(phi)

    basis = np.column_stack((np.ones_like(azimuth), np.cos(azimuth), np.sin(azimuth)))
    arms = np.vstack((np.ones_like(radii), radii * np.sin(azimuth), -radii * np.cos(azimuth)))
    scales = np.array([thrust, thrust * radius, thrust * radius])
    target = np.array([thrust, roll_moment, pitch_moment])

    def forces(controls):
        cl = lift_slope * (basis @ controls - phi)
        cd = cd0 + .012 * cl * cl
        normal = q * (cl * cos_phi - cd * sin_phi)
        loads = arms @ normal
        torque = np.sum(q * (cl * sin_phi + cd * cos_phi) * radii)
        gradient = q * lift_slope * (cos_phi - .024 * cl * sin_phi)
        jacobian = arms @ (gradient[:, None] * basis)
        return loads, float(torque), float(np.max(np.abs(cl))), jacobian

    controls = np.array([.1, 0., 0.])
    for _ in range(20):
        loads, torque, cl, jacobian = forces(controls)
        residual = (loads - target) / scales
        if np.max(np.abs(residual)) < 1e-9:
            break
        try:
            controls -= np.linalg.solve(jacobian / scales[:, None], residual)
        except np.linalg.LinAlgError as exc:
            raise ValueError("Singular rotor trim equations") from exc
    else:
        raise ValueError("Rotor collective/cyclic trim did not converge")
    if not -.1 <= controls[0] <= .5 or np.linalg.norm(controls[1:]) > .25:
        raise ValueError("Rotor collective/cyclic control limits exceeded")
    if torque <= 0:
        raise ValueError("Autorotative operating points are outside the powered-rotor model")
    return {"power": torque * omega, "torque": torque, "collective": float(controls[0]),
            "cyclic_cos": float(controls[1]), "cyclic_sin": float(controls[2]),
            "thrust": float(loads[0]), "roll_moment": float(loads[1]), "pitch_moment": float(loads[2]),
            "max_cl": cl, "trim_residual": float(np.max(np.abs(residual))), "tip_speed": tip}


def helicopter_trim(weight, speed, climb, drag, rho, radius, rpm, blades, chord, cd0,
                    tail_arm, hub_x=0., hub_z=.15, tail_z=.15):
    """Six-component steady equilibrium for a rigid single-main-rotor aircraft.

    Main disk attitude resolves weight, parasite drag and tail side force. Cyclic
    hub moments balance the moments of those forces; tail thrust balances the
    remaining component along the main disk normal, including main shaft torque.
    """
    import numpy as np
    from scipy.optimize import brentq
    if weight <= 0 or tail_arm <= 0 or drag < 0:
        raise ValueError("Invalid helicopter trim inputs")
    hub = np.array([hub_x, 0., hub_z])
    tail_position = np.array([-tail_arm, 0., tail_z])
    velocity = np.array([speed, 0., climb])

    def state(tail):
        force = np.array([drag, tail, weight])
        thrust = float(np.linalg.norm(force))
        normal = force / thrust
        disk_x = np.array([1., 0., 0.]) - normal[0] * normal
        disk_x /= np.linalg.norm(disk_x)
        disk_y = np.cross(normal, disk_x)
        tail_force = np.array([0., -tail, 0.])
        force_moments = np.cross(hub, force) + np.cross(tail_position, tail_force)
        mx, my = -float(force_moments @ disk_x), -float(force_moments @ disk_y)
        axial = float(velocity @ normal)
        tangential = float(np.linalg.norm(velocity - axial * normal))
        rotor = rotor_performance(thrust, tangential, rho, radius, rpm, blades, chord, cd0,
                                  roll_moment=mx, pitch_moment=my, axial_speed=axial)
        moment = force_moments + rotor["roll_moment"] * disk_x + rotor["pitch_moment"] * disk_y - rotor["torque"] * normal
        return float(moment @ normal), rotor, force, tail_force, moment, normal

    low = state(0.)[0]
    hi = max(weight * .01, .01)
    while hi <= weight:
        high = state(hi)[0]
        if low * high <= 0:
            break
        hi *= 2
    else:
        raise ValueError("Helicopter tail thrust could not close steady moment balance")
    tail = brentq(lambda value: state(value)[0], 0., hi, xtol=1e-10)
    _, rotor, force, tail_force, moment, normal = state(tail)
    force_residual = force + tail_force + np.array([-drag, 0., -weight])
    residual = max(float(np.max(np.abs(force_residual))) / weight,
                   float(np.max(np.abs(moment))) / (weight * radius), rotor["trim_residual"])
    if residual > 1e-6:
        raise ValueError("Helicopter steady force/moment trim failed residual tolerance")
    return {**rotor, "tail_thrust": tail, "main_thrust": float(np.linalg.norm(force)),
            "disk_pitch": math.atan2(normal[0], normal[2]), "disk_roll": math.atan2(normal[1], normal[2]),
            "aircraft_trim_residual": residual,
            **{f"force_residual_{axis}": float(value) for axis, value in zip("xyz", force_residual)},
            **{f"moment_residual_{axis}": float(value) for axis, value in zip("xyz", moment)}}
