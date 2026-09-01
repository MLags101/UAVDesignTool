"""
Takeoff and Landing Distance

Ground roll, obstacle clearance and landing distance, plus the two launch
methods models actually use: hand launch and bungee. The hand-launch check is
the one that matters most in practice, because a model that cannot accelerate
faster than it decelerates after leaving the hand will simply mush into the
ground.
"""

import math

from uavlib import aero, atmosphere, report, units
from uavlib.atmosphere import G

TOOL_METADATA = {
    "name": "Takeoff & Landing Distance",
    "category": "Fixed Wing / Performance",
    "description": (
        "Ground roll, 15 m obstacle distance and landing distance for a given "
        "thrust and surface. Also checks hand launch feasibility and sizes a "
        "bungee launch."
    ),
    "inputs": [
        {"key": "mass", "label": "Total Mass", "unit": "kg", "type": "number"},
        {"key": "wing_area", "label": "Wing Area (S)", "unit": "m^2",
         "type": "number"},
        {"key": "cl_max", "label": "Max Lift Coefficient", "type": "number",
         "default": "1.2"},
        {"key": "cl_ground", "label": "Ground Roll CL", "type": "number",
         "default": "0.5",
         "help": "Lift coefficient at the ground attitude, before rotation."},
        {"key": "cd0", "label": "Parasite Drag (CD0)", "type": "number",
         "default": "0.045", "help": "Include the undercarriage."},
        {"key": "aspect_ratio", "label": "Aspect Ratio", "type": "number",
         "default": "8"},
        {"key": "static_thrust", "label": "Static Thrust", "unit": "N",
         "type": "number", "help": "Accepts 'gf'. From the prop matching tool."},
        {"key": "surface", "label": "Surface", "type": "choice",
         "choices": ["Smooth paved", "Short grass", "Long grass", "Dirt / gravel"],
         "default": "Short grass"},
        {"key": "altitude", "label": "Field Elevation", "unit": "m",
         "type": "number", "default": "0"},
        {"key": "headwind", "label": "Headwind", "unit": "m/s", "type": "number",
         "default": "0"},
        {"key": "launch_method", "label": "Launch Method", "type": "choice",
         "choices": ["Ground roll", "Hand launch", "Bungee"],
         "default": "Ground roll"},
        {"key": "hand_launch_speed", "label": "Hand Launch Speed", "unit": "m/s",
         "type": "number", "default": "8",
         "help": "Realistically 7-10 m/s for an adult with a light model."},
    ],
}

# Rolling friction coefficients, and braking values for the landing case.
SURFACES = {
    "Smooth paved":  {"roll": 0.03, "brake": 0.40},
    "Short grass":   {"roll": 0.07, "brake": 0.30},
    "Long grass":    {"roll": 0.12, "brake": 0.25},
    "Dirt / gravel": {"roll": 0.09, "brake": 0.30},
}

OBSTACLE_HEIGHT = 15.0  # m, the conventional screen height


def run(inputs):
    try:
        mass = units.positive(inputs, "mass", "kg", "Mass")
        wing_area = units.positive(inputs, "wing_area", "m^2", "Wing area")
        cl_max = units.positive(inputs, "cl_max", "", "CLmax", default=1.2)
        cl_ground = units.optional(inputs, "cl_ground", "", 0.5)
        cd0 = units.positive(inputs, "cd0", "", "CD0", default=0.045)
        aspect_ratio = units.positive(inputs, "aspect_ratio", "", "Aspect ratio",
                                      default=8.0)
        thrust = units.positive(inputs, "static_thrust", "N", "Static thrust")
        surface_name = inputs.get("surface") or "Short grass"
        altitude = units.optional(inputs, "altitude", "m", 0.0)
        headwind = units.optional(inputs, "headwind", "m/s", 0.0)
        method = inputs.get("launch_method") or "Ground roll"
        hand_speed = units.optional(inputs, "hand_launch_speed", "m/s", 8.0)

        air = atmosphere.at(altitude)
        rho = air.density
        weight = mass * G
        surface = SURFACES[surface_name]
        oswald = aero.oswald_efficiency(aspect_ratio)
        k = aero.induced_drag_factor(aspect_ratio, oswald)

        v_stall = aero.stall_speed(mass, wing_area, cl_max, altitude)
        v_rotate = 1.1 * v_stall
        v_liftoff = 1.2 * v_stall
        v_approach = 1.3 * v_stall
        v_touchdown = 1.1 * v_stall

        def ground_acceleration(v):
            """Net acceleration during the roll at speed v."""
            q = 0.5 * rho * v ** 2
            lift = q * wing_area * cl_ground
            drag = q * wing_area * (cd0 + k * cl_ground ** 2)
            normal = max(0.0, weight - lift)
            friction = surface["roll"] * normal
            # Thrust falls off with speed as the propeller unloads.
            available = thrust * max(0.3, 1.0 - 0.35 * (v / max(v_liftoff, 1e-6)))
            return (available - drag - friction) / mass

        # Integrate the ground roll numerically, in airspeed.
        v_start = headwind
        v = v_start
        distance = 0.0
        time = 0.0
        step = 0.01
        stalled = False
        while v < v_liftoff:
            acceleration = ground_acceleration(v)
            if acceleration <= 0.05:
                stalled = True
                break
            ground_speed = max(v - headwind, 0.0)
            distance += ground_speed * step
            v += acceleration * step
            time += step
            if time > 120:
                stalled = True
                break

        r = report.Report("Takeoff & Landing")
        r.section("Conditions")
        r.dual("Mass", mass, "kg", "lb", 3)
        r.value("Field elevation", altitude, "m", 0)
        r.value("Air density", rho, "kg/m^3", 4)
        r.value("Density altitude", atmosphere.density_altitude(rho), "m", 0)
        r.value("Surface", surface_name,
                note=f"friction {surface['roll']:.2f}")
        r.dual("Headwind", headwind, "m/s", "mph", 2)
        r.value("Static thrust", thrust, "N", 2)
        r.value("Thrust-to-weight", thrust / weight, ":1", 3)

        r.section("Speeds")
        r.dual("Stall speed", v_stall, "m/s", "mph", 2)
        r.dual("Rotate (1.1 Vs)", v_rotate, "m/s", "mph", 2)
        r.dual("Liftoff (1.2 Vs)", v_liftoff, "m/s", "mph", 2)
        r.dual("Approach (1.3 Vs)", v_approach, "m/s", "mph", 2)
        r.dual("Touchdown (1.1 Vs)", v_touchdown, "m/s", "mph", 2)

        if method == "Hand launch":
            r.section("Hand Launch")
            q = 0.5 * rho * hand_speed ** 2
            cl_needed = weight / (q * wing_area) if q > 0 else float("inf")
            drag = q * wing_area * (cd0 + k * min(cl_needed, cl_max) ** 2)
            net = thrust - drag
            r.dual("Launch speed", hand_speed, "m/s", "mph", 2)
            r.value("Launch speed / stall", hand_speed / v_stall, "", 2)
            r.value("CL needed to sustain", cl_needed, "", 3)
            r.value("CLmax available", cl_max, "", 3)
            r.value("Drag at launch", drag, "N", 2)
            r.value("Net accelerating force", net, "N", 2)
            r.value("Initial acceleration", net / mass, "m/s^2", 2)

            if hand_speed < v_stall:
                r.warn(f"Launch speed is below the stall speed "
                       f"({v_stall:.1f} m/s). The model cannot fly away and "
                       "will drop.")
            elif hand_speed < v_stall * 1.15:
                r.warn("Very marginal: less than 15% above the stall. Any "
                       "mishandling on release will end in a stall.")
            else:
                r.bullet("Launch speed gives adequate margin above the stall.")

            if net <= 0:
                r.warn("Thrust does not exceed drag at launch speed. The model "
                       "will decelerate after release and sink.")
            else:
                r.value("Time to reach climb speed",
                        max(0.0, (v_liftoff - hand_speed) / (net / mass)), "s", 2)
            r.bullet("Launch into wind, nose level or very slightly down, and "
                     "with full power already applied.")

        elif method == "Bungee":
            r.section("Bungee Launch")
            target = v_liftoff * 1.15
            energy = 0.5 * mass * target ** 2
            r.dual("Target release speed", target, "m/s", "mph", 2)
            r.value("Kinetic energy needed", energy, "J", 1)
            for stretch in (5.0, 10.0, 15.0):
                force = energy / stretch
                r.value(f"Average force over {stretch:g} m", force, "N", 1,
                        note=f"{force / weight:.1f}x weight")
            r.bullet("Aim for an average acceleration below about 5 g; higher "
                     "loads risk pulling the hook out or folding a wing.")
            acceleration = target ** 2 / (2 * 10.0)
            r.value("Acceleration over a 10 m run", acceleration / G, "g", 2)

        else:
            r.section("Ground Roll")
            if stalled:
                r.warn("The aircraft cannot accelerate to liftoff speed on this "
                       "surface. Thrust is insufficient against drag and "
                       "rolling friction.")
                r.bullet("Try a smoother surface, more thrust, a lighter model "
                         "or a larger wing.")
            else:
                r.value("Ground roll", distance, "m", 1)
                r.value("  in feet", distance / 0.3048, "ft", 1)
                r.value("Time to liftoff", time, "s", 2)
                r.value("Average acceleration", v_liftoff / time if time else 0,
                        "m/s^2", 2)

                # Climb over the obstacle at best angle.
                q = 0.5 * rho * v_liftoff ** 2
                cl = weight / (q * wing_area)
                drag = q * wing_area * aero.drag_polar(cl, cd0, k)
                climb_angle = math.asin(max(-1.0, min(1.0,
                                                      (thrust - drag) / weight)))
                if climb_angle > 0.01:
                    air_distance = OBSTACLE_HEIGHT / math.tan(climb_angle)
                    r.blank()
                    r.value("Climb angle", math.degrees(climb_angle), "deg", 1)
                    r.value(f"Air distance to {OBSTACLE_HEIGHT:g} m",
                            air_distance, "m", 1)
                    r.value("Total takeoff distance", distance + air_distance,
                            "m", 1)
                else:
                    r.warn("Cannot climb after liftoff: drag exceeds thrust at "
                           "liftoff speed.")

                if headwind > 0:
                    still_air = distance * (1 + headwind / v_liftoff) ** 2
                    r.blank()
                    r.value("Ground roll in still air", still_air, "m", 1,
                            note="for comparison")

        r.section("Landing")
        # Deceleration from touchdown, braking plus aerodynamic drag.
        q_touch = 0.5 * rho * v_touchdown ** 2
        drag_touch = q_touch * wing_area * (cd0 + k * cl_ground ** 2)
        lift_touch = q_touch * wing_area * cl_ground
        braking = surface["brake"] * max(0.0, weight - lift_touch)
        deceleration = (drag_touch + braking) / mass
        ground_touchdown = max(v_touchdown - headwind, 0.1)
        landing_roll = ground_touchdown ** 2 / (2 * deceleration) \
            if deceleration > 0 else float("inf")

        r.dual("Touchdown speed", v_touchdown, "m/s", "mph", 2)
        r.value("Braking coefficient", surface["brake"], "", 2)
        r.value("Average deceleration", deceleration, "m/s^2", 2)
        r.value("Landing ground roll", landing_roll, "m", 1)
        r.value("  in feet", landing_roll / 0.3048, "ft", 1)
        approach_distance = OBSTACLE_HEIGHT / math.tan(math.radians(6.0))
        r.value(f"Air distance from {OBSTACLE_HEIGHT:g} m at 6 deg",
                approach_distance, "m", 1)
        r.value("Total landing distance", landing_roll + approach_distance, "m", 1)

        r.section("Notes")
        r.bullet("Distances scale with the square of the density ratio: a hot "
                 "day at elevation lengthens the roll noticeably.")
        if altitude > 500:
            sea_level = distance * (atmosphere.RHO_0 / rho) if not stalled else 0
            if sea_level:
                r.bullet(f"At sea level this roll would be about "
                         f"{sea_level:.0f} m, against {distance:.0f} m here.")
        r.bullet("Headwind shortens both takeoff and landing roughly in "
                 "proportion to the square of the groundspeed reduction.")

        outputs = {
            "Stall Speed": {"value": v_stall, "unit": "m/s"},
            "Liftoff Speed": {"value": v_liftoff, "unit": "m/s"},
            "Landing Roll": {"value": landing_roll, "unit": "m"},
        }
        if method == "Ground roll" and not stalled:
            outputs["Takeoff Ground Roll"] = {"value": distance, "unit": "m"}

        return report.result(r, outputs=outputs)

    except units.UnitError as exc:
        return report.error(str(exc))
    except ValueError as exc:
        return report.error(str(exc))
    except Exception as exc:
        return report.error(f"executing tool: {exc}")
