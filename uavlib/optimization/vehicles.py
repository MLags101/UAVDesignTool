"""Coupled conceptual evaluators. All outputs are SI, no GUI state is used."""
import math
from copy import deepcopy
from uavlib.propulsion import profile_power_factor
from uavlib.structures import required_spar_cap_area
from .physics import atmosphere, axial_induced_power, battery_operating_point, ideal_hover, interpolate, helicopter_trim, transition_forces
from .schema import EvaluationResult
from .templates import PARAMETERS, METRICS
from .propulsion import electric_drive, motor_operating_point

G = 9.80665
REGISTRY = {}


def register_model(name, model):
    """Register a headless model with evaluate(study, parameters) and discovery."""
    REGISTRY[name] = model


def positive(p, *names):
    for name in names:
        if name not in p or not math.isfinite(p[name]) or p[name] <= 0:
            raise ValueError(f"{name} must be finite and positive")


def assembly(study, p):
    """Resolve installed hardware without mutating any component or source map."""
    a, components = study.vehicle.assumptions, study.vehicle.components
    hardware = study.workflow == "hardware"
    result = dict(mass=0., moment=0., power=p["installed_power"], energy=p["energy_capacity"],
                  fuel=p["fuel_mass"], voltage=a["voltage"], resistance=a["resistance"],
                  max_current=a["max_current"], min_voltage=a["min_voltage"],
                  prop_efficiency_map=None, engine_map=None, battery_mass=0., fuel_position=0.)
    if not hardware:
        return result
    if not components:
        raise ValueError("Hardware-first study needs explicit installed components")
    kinds = {c.kind for c in components}
    required = {"motor", "battery", "controller", "propeller"} if study.vehicle.propulsion == "electric" else {"engine", "tank", "propeller"}
    if study.vehicle.family == "helicopter":
        required.discard("propeller")
        required |= {"main_rotor", "tail_rotor", "transmission"}
    if study.vehicle.family == "lift_cruise":
        required |= {"lift_motor", "lift_rotor", "battery", "controller"}
    if study.vehicle.propulsion == "fuel" and study.vehicle.family == "multirotor":
        required.add("transmission")
    missing = required - kinds
    if missing:
        raise ValueError("Missing hardware: " + ", ".join(sorted(missing)))
    result.update(power=0., energy=0., fuel=0., max_current=float("inf"))
    engines = [c for c in components if c.kind == "engine"]
    if len(engines) > 1 or any(c.quantity != 1 for c in engines):
        raise ValueError("Describe the fuel engine/drivetrain as one aggregate mapped assembly")
    batteries = [c for c in components if c.kind == "battery"]
    if len(batteries) > 1:
        raise ValueError("Describe the wired battery assembly as one aggregate battery record")
    for c in components:
        props = c.properties
        mass = c.mass * c.quantity
        position = p.get(f"component.{c.id}.position", c.position)
        result["mass"] += mass
        result["moment"] += mass * position
        if c.kind in ("motor", "engine"):
            if props["max_power"] <= 0:
                raise ValueError("Installed power must be positive")
            result["power"] += props["max_power"] * c.quantity
            if c.kind == "engine":
                result["engine_map"] = props["fuel_flow_map"]
        if c.kind == "battery":
            if c.quantity != 1:
                raise ValueError("Battery aggregate quantity must be one; encode pack wiring in its ratings")
            result.update(energy=props["energy"], voltage=props["voltage"],
                          resistance=props["resistance"], min_voltage=props["min_voltage"],
                          battery_mass=mass, ocv_map=props.get("ocv_map"), resistance_map=props.get("resistance_map"))
            result["max_current"] = min(result["max_current"], props["max_current"])
            if min(props["energy"], props["voltage"], props["min_voltage"], props["max_current"]) <= 0 or props["resistance"] < 0:
                raise ValueError("Invalid battery assembly ratings")
        if c.kind == "controller":
            result["max_current"] = min(result["max_current"], props["max_current"] * c.quantity)
        if c.kind == "tank":
            if props["fuel_mass"] < 0:
                raise ValueError("Tank fuel mass must be nonnegative")
            added_fuel = props["fuel_mass"] * c.quantity
            total_fuel = result["fuel"] + added_fuel
            result["fuel_position"] = ((result["fuel_position"] * result["fuel"] + position * added_fuel) /
                                       total_fuel) if total_fuel else 0.
            result["fuel"] = total_fuel
        if c.kind == "propeller":
            if study.vehicle.family != "lift_cruise":
                p["rotor_diameter"] = props["diameter"]
            result["prop_efficiency_map"] = props.get("efficiency_map")
            result["power_map"] = props.get("max_power_map")
            result["propeller_quantity"] = c.quantity
            if study.vehicle.family in ("fixed_wing", "lift_cruise") and not result["power_map"] and not props.get("performance_map"):
                raise ValueError("Cruise propeller needs a measured airspeed/available shaft power envelope")
            if study.vehicle.family in ("fixed_wing", "lift_cruise") and not result["prop_efficiency_map"] and not props.get("performance_map"):
                raise ValueError("Cruise propeller needs an airspeed/efficiency map")
        if c.kind in ("main_rotor", "lift_rotor"):
            for key, prop in (("rotor_diameter", "diameter"), ("blade_chord", "chord"),
                              ("blade_count", "blades"), ("rotor_rpm", "rpm")):
                p[key] = props[prop]
            result["rotor_quantity"] = c.quantity
        if c.kind == "tail_rotor":
            p["tail_rotor_diameter"] = props["diameter"]
        if c.kind == "transmission":
            result["transmission_limit"] = props["max_power"]
        if c.kind == "lift_motor":
            result["lift_power"] = props["max_power"] * c.quantity
        if c.kind == "wing":
            p["wing_area"], p["aspect_ratio"] = props["area"], props["aspect_ratio"]
            result["fixed_wing"] = True
            result["wing_cap_area"] = props["spar_cap_area"]
            result["wing_spar_depth"] = props["spar_depth"]
            if min(result["wing_cap_area"], result["wing_spar_depth"]) <= 0:
                raise ValueError("Installed wing needs positive spar cap area and depth for strength checks")
        if c.kind == "frame":
            for key in ("arm_length", "arm_diameter", "arm_wall"):
                p[key] = props[key]
            result["fixed_frame"] = True
    if "transmission_limit" in result:
        result["power"] = min(result["power"], result["transmission_limit"])
    mapped = [c for c in components if c.kind == "propeller" and c.properties.get("performance_map")]
    if mapped:
        motors = [c for c in components if c.kind == "motor"]
        controllers = [c for c in components if c.kind == "controller"]
        if study.vehicle.propulsion != "electric" or study.vehicle.family not in ("fixed_wing", "lift_cruise", "multirotor"):
            raise ValueError("Measured axial propeller maps require electric propeller-driven aircraft")
        if len(mapped) != 1 or len(motors) != 1 or len(controllers) != 1:
            raise ValueError("Mapped drive needs one record each for identical propellers, motors and controllers")
        if not mapped[0].quantity == motors[0].quantity == controllers[0].quantity:
            raise ValueError("Mapped drive motor, propeller and controller quantities must match")
        result["drive"] = (mapped[0], motors[0], controllers[0])
    motors = [c for c in components if c.kind == "motor" and "kv_rpm_per_volt" in c.properties]
    if motors and study.vehicle.family != "helicopter" and not mapped:
        raise ValueError("Motor terminal constants need a matching propeller performance_map")
    if study.vehicle.family == "helicopter" and motors:
        controllers = [c for c in components if c.kind == "controller"]
        transmissions = [c for c in components if c.kind == "transmission"]
        if len(motors) != 1 or motors[0].quantity != 1 or len(controllers) != 1 or len(transmissions) != 1:
            raise ValueError("Helicopter motor circuit requires one aggregate motor/controller/transmission")
        ratio = transmissions[0].properties["motor_to_rotor_ratio"]
        if ratio <= 0:
            raise ValueError("Motor-to-rotor speed ratio must be positive")
        result["motor_drive"] = (motors[0], controllers[0], ratio)
    return result


class AircraftModel:
    parameters = PARAMETERS
    metrics = METRICS

    def evaluate(self, study, p):
        a = study.vehicle.assumptions
        family = study.vehicle.family
        fuelled = study.vehicle.propulsion == "fuel"
        if study.vehicle.propulsion not in ("electric", "fuel"):
            raise ValueError("Propulsion must be electric or fuel")
        if not study.mission.segments:
            raise ValueError("Aircraft mission needs at least one segment")
        base_duration = sum(s.duration for s in study.mission.segments)
        duration_scale = p.get("mission_duration", base_duration) / base_duration
        if duration_scale <= 0:
            raise ValueError("Mission duration must be positive")
        positive(p, "wing_area", "aspect_ratio", "rotor_diameter", "arm_length", "tail_arm")
        if p.get("storage_margin", 1.) < 1 or p.get("power_margin", a["power_margin"]) < 1 or p.get("structure_margin", 1.) < 1:
            raise ValueError("Sizing storage/power margins must be at least one")
        for key in ("specific_energy", "allowable_stress", "material_density", "modulus", "max_mass"):
            positive(a, key)
        positive(a, "cl_max", "load_factor", "spar_depth_fraction", "deflection_fraction", "power_margin",
                 "closure_tolerance", "min_voltage", "max_current", "voltage", "tail_efficiency")
        if min(a["cd0"], a["fixed_mass"], a["wing_areal_mass"], a["power_specific_mass"], a["fuel_sfc"], a["flat_plate_area"]) < 0:
            raise ValueError("Mass, fuel-consumption and drag assumptions must be nonnegative")
        if p["payload"] < 0:
            raise ValueError("Payload cannot be negative")
        for key in ("oswald", "efficiency", "motor_efficiency", "figure_of_merit", "usable_fraction", "transmission_efficiency"):
            if not 0 < a[key] <= 1:
                raise ValueError(f"{key} must be in (0, 1]")
        if p["aspect_ratio"] > 16:
            raise ValueError("Aspect ratio exceeds this conceptual polar's validated domain (16)")
        hw = assembly(study, p)
        sizing = study.workflow == "requirements" and "_fixed_power" not in p
        winged = family in ("fixed_wing", "lift_cruise")
        # Layout metadata from the existing library is used below via explicit counts.
        counts = {"quad_x": 4, "quad_plus": 4, "quad_h": 4, "hex": 6, "hexa": 6,
                  "y6": 6, "octo": 8, "x8": 8, "tri": 3}
        if study.vehicle.layout not in counts:
            raise ValueError("Unknown rotor layout")
        count = 1 if family == "helicopter" else counts[study.vehicle.layout]
        if family == "multirotor" and hw.get("propeller_quantity", count) != count:
            raise ValueError("Installed propeller quantity does not match the selected topology")
        if hw.get("rotor_quantity") and hw["rotor_quantity"] != count:
            raise ValueError("Installed rotor quantity does not match the selected topology")
        coaxial = study.vehicle.layout in ("y6", "x8")
        disks = count // 2 if coaxial else count
        area = disks * math.pi * (p["rotor_diameter"] / 2) ** 2
        if family in ("multirotor", "lift_cruise"):
            positive(p, "arm_diameter", "arm_wall")
            if 2 * p["arm_wall"] >= p["arm_diameter"]:
                raise ValueError("Arm wall must be less than half its outer diameter")
        span = math.sqrt(p["wing_area"] * p["aspect_ratio"])
        chord = p["wing_area"] / span
        mass = p.get("_fixed_takeoff_mass", max(p["payload"] + hw["mass"] + a["fixed_mass"] + 1., .1))
        reserve = study.mission.reserve_fraction
        available_power = p.get("_fixed_power", hw["power"])
        available_lift_power = p.get("_fixed_lift_power", hw.get("lift_power", p["installed_power"])) if family == "lift_cruise" else 0.
        energy_capacity = p.get("_fixed_energy", hw["energy"])
        fuel_capacity = p.get("_fixed_fuel", hw["fuel"])
        residual = 0.
        history = []
        rotor_state = {}
        transition_state = {}
        drive_state = {}
        drive_cache = {}

        def mapped_power(thrust, speed, density):
            prop, motor, controller = hw["drive"]
            if thrust <= 0:
                drive_state.update(bus_power=0., motor_voltage=0., motor_current=0., rpm=0.,
                                   motor_current_margin=1., controller_current_margin=1., motor_power_margin=1.)
                return 0.
            key = (thrust, speed, density)
            if key not in drive_cache:
                drive_cache[key] = electric_drive(thrust / prop.quantity, speed, density,
                                                 prop.properties, motor.properties, controller.properties)
            drive_state.update(drive_cache[key])
            drive_state["bus_power"] *= prop.quantity
            return drive_state["shaft_power"] * prop.quantity

        def calculate_shaft_power(m, v, h, climb, kind, fraction=1., acceleration=0., cg_position=0.):
            rho = atmosphere(h).density
            weight = m * G
            tail_power = 0.
            blade_margin = tip_margin = 1.
            eta = interpolate(hw["prop_efficiency_map"], v) if hw["prop_efficiency_map"] and v > 0 else a["efficiency"]
            if not 0 < eta <= 1:
                raise ValueError("Propeller efficiency must be in (0, 1]")
            cruise = 0.
            drag = 0.
            if winged and v > 0:
                q = .5 * rho * v * v
                cl = weight * fraction / (q * p["wing_area"])
                cd = a["cd0"] + cl * cl / (math.pi * a["oswald"] * p["aspect_ratio"])
                drag = q * p["wing_area"] * cd
                if family == "lift_cruise":
                    drag += q * a["flat_plate_area"]
                cruise = drag * v / eta
            if family == "fixed_wing" or (family == "lift_cruise" and kind == "cruise"):
                if v <= 0:
                    raise ValueError("Wing-borne segment requires positive airspeed")
                requested = cruise + max(0., weight * climb / eta)
                if "drive" in hw:
                    requested = mapped_power(drag + max(0., weight * climb / v), v, rho)
                return requested, tail_power, blade_margin, tip_margin, 0.
            if family == "helicopter":
                rotor = helicopter_trim(weight, v, climb, .5 * rho * v*v * a["flat_plate_area"], rho,
                                        p["rotor_diameter"] / 2, p["rotor_rpm"], p["blade_count"], p["blade_chord"],
                                        a["rotor_profile_cd"], p["tail_rotor_arm"],
                                        p.get("main_rotor_x", .3 * chord) - cg_position,
                                        p.get("main_rotor_height", .15), p.get("tail_rotor_height", .15))
                rotor_state.update(rotor_collective=rotor["collective"],
                                   rotor_cyclic_cos=rotor["cyclic_cos"], rotor_cyclic_sin=rotor["cyclic_sin"],
                                   rotor_trim_residual=rotor["trim_residual"],
                                   rotor_roll_moment=rotor["roll_moment"], rotor_pitch_moment=rotor["pitch_moment"],
                                   main_rotor_torque=rotor["torque"])
                rotor_state.update({key: value for key, value in rotor.items() if key.startswith(("force_residual_", "moment_residual_", "disk_", "aircraft_trim_"))})
                tail_thrust = rotor["tail_thrust"]
                tail_power = ideal_hover(tail_thrust, rho, math.pi * (p["tail_rotor_diameter"] / 2) ** 2) / a["tail_efficiency"]
                blade_margin = a["max_blade_cl"] - rotor["max_cl"]
                tip_margin = a["tip_mach_limit"] - (rotor["tip_speed"] + v) / atmosphere(h).sound_speed
                power = (rotor["power"] + tail_power) / a["transmission_efficiency"]
                if "motor_drive" in hw:
                    motor, controller, ratio = hw["motor_drive"]
                    drive_state.update(motor_operating_point(power, p["rotor_rpm"] * ratio, motor.properties, controller.properties))
                return power, tail_power, blade_margin, tip_margin, 0.
            if v > 22:
                raise ValueError("Multirotor power model limited to 22 m/s")
            lift_fraction = 1. - fraction if kind == "transition" else 1.
            thrust = weight * lift_fraction
            if family == "multirotor" and "drive" in hw:
                if v > 0 or coaxial or climb < 0:
                    raise ValueError("Axial propeller maps support independent-rotor hover/climb only; edgewise, coaxial and descent data are required for other flight")
                return mapped_power(thrust, climb, rho), tail_power, blade_margin, tip_margin, 0.
            if kind == "transition":
                forces = transition_forces(m, weight * fraction, drag, acceleration)
                transition_state.update(forces)
                thrust = forces["lift_thrust"]
                cruise = forces["cruise_thrust"] * v / eta
                if "drive" in hw:
                    cruise = mapped_power(forces["cruise_thrust"], v, rho)
            axial = thrust > 0 and v <= 1e-8 and climb >= 0
            if thrust <= 0:
                rotor_power = 0.
            else:
                vh = math.sqrt(thrust / (2 * rho * area))
                profile = ideal_hover(thrust, rho, area) * (1 / a["figure_of_merit"] - 1) * profile_power_factor(v, vh)
                if axial:
                    induced, _vi = axial_induced_power(thrust, climb, rho, area)
                else:
                    induced = thrust * math.sqrt((math.sqrt(v ** 4 + 4 * vh ** 4) - v * v) / 2)
                rotor_power = (induced + profile) / (.8 if coaxial else 1.)
            # Axial momentum already contains the climb term. Edgewise flight
            # still adds potential power on top of the level-flight induced power.
            lift_power = rotor_power if axial else rotor_power + max(0., weight * climb)
            total = lift_power + (cruise if kind == "transition" else .5 * rho * v ** 3 * a["flat_plate_area"])
            if fuelled and family == "multirotor":
                total /= a["transmission_efficiency"]
            return total, tail_power, blade_margin, tip_margin, lift_power if family == "lift_cruise" else 0.

        shaft_cache = {}

        def shaft_power(*args):
            if args not in shaft_cache:
                rotor_state.clear()
                drive_state.clear()
                transition_state.clear()
                answer = calculate_shaft_power(*args)
                if len(shaft_cache) >= 1024:
                    shaft_cache.clear()
                shaft_cache[args] = (answer, dict(rotor_state), dict(drive_state), dict(transition_state))
            answer, rotor_data, drive_data, transition_data = shaft_cache[args]
            rotor_state.clear()
            rotor_state.update(rotor_data)
            drive_state.clear()
            drive_state.update(drive_data)
            transition_state.clear()
            transition_state.update(transition_data)
            return answer

        for iteration in range(120):
            # Two-cap spar. Stress and deflection share one section inertia.
            depth = hw.get("wing_spar_depth", a["spar_depth_fraction"] * chord)
            caps = required_spar_cap_area(mass * G * a["load_factor"], span, depth,
                                          a["allowable_stress"], a["modulus"], a["deflection_fraction"])
            cap_stress, cap_deflect = caps["stress"], caps["deflection"]
            cap_area = max(cap_stress, cap_deflect, 1e-6) * p.get("structure_margin", 1.)
            if "_fixed_cap_area" in p:
                cap_area = p["_fixed_cap_area"]
            if hw.get("fixed_wing"):
                cap_area = hw["wing_cap_area"]
            structure = 2 * cap_area * span * a["material_density"] if winged else mass * .08
            structural_margin = 0.
            if winged:
                structural_margin = min(cap_area / max(cap_stress, 1e-12) - 1,
                                        cap_area / max(cap_deflect, 1e-12) - 1)
            arm_mass = 0.
            if family in ("multirotor", "lift_cruise"):
                outer, inner = p["arm_diameter"], p["arm_diameter"] - 2 * p["arm_wall"]
                section = math.pi * (outer ** 2 - inner ** 2) / 4
                inertia = math.pi * (outer ** 4 - inner ** 4) / 64
                force = mass * G * a["load_factor"] / disks
                stress = force * p["arm_length"] * outer / (2 * inertia)
                deflection = force * p["arm_length"] ** 3 / (3 * a["modulus"] * inertia)
                arm_margin = min(a["allowable_stress"] / stress - 1,
                                 a["deflection_fraction"] * p["arm_length"] / deflection - 1)
                structural_margin = min(structural_margin, arm_margin) if winged else arm_margin
                arm_mass = disks * section * p["arm_length"] * a["material_density"]
                if not hw.get("fixed_frame"):
                    structure += arm_mass
            shell = a["wing_areal_mass"] * (p["wing_area"] + p["tail_area"]) if winged else .15 * count * p["rotor_diameter"]
            if hw.get("fixed_wing"):
                shell -= a["wing_areal_mass"] * p["wing_area"]
                structure -= 2 * cap_area * span * a["material_density"]
            empty = a["fixed_mass"] + shell + structure
            if "_fixed_airframe_mass" in p:
                empty = p["_fixed_airframe_mass"]
            energy = used_fuel = peak = peak_current = tail_peak = transition_energy = 0.
            peak_main = peak_lift = 0.
            min_voltage = hw["voltage"]
            blade_margin = tip_margin = 1.
            history = []
            elapsed = 0.
            min_power_margin = float("inf")
            min_stall_margin = float("inf")
            for segment in study.mission.segments:
                if segment.kind not in ("cruise", "hover", "climb", "descent", "transition", "manual"):
                    raise ValueError(f"Unsupported mission kind {segment.kind}")
                if segment.kind == "transition" and family != "lift_cruise":
                    raise ValueError("Transition segment is for lift-plus-cruise only")
                actual_duration = segment.duration * duration_scale
                steps = max(1, math.ceil(actual_duration / 10))
                dt = actual_duration / steps
                for j in range(steps):
                    drive_state.clear()
                    frac = (j + .5) / steps
                    v = p["cruise_speed"] if segment.kind == "cruise" else segment.speed
                    h = segment.altitude
                    fraction = 1.
                    acceleration = 0.
                    if segment.kind == "transition":
                        end = segment.end_speed if segment.end_speed is not None else p["cruise_speed"]
                        v = segment.speed + frac * (end - segment.speed)
                        acceleration = (end - segment.speed) / actual_duration
                        if segment.end_altitude is not None:
                            h += frac * (segment.end_altitude - segment.altitude)
                        fraction = min(.95, .5 * atmosphere(h).density * v * v * p["wing_area"] * a["cl_max"] / (mass * G))
                    m = mass - used_fuel
                    if m <= 0:
                        raise ValueError("Mission consumed more fuel than vehicle mass")
                    if segment.kind == "manual":
                        if "drive" in hw or "motor_drive" in hw:
                            raise ValueError("Mapped electric drives need flight conditions, not a manual power budget")
                        if segment.power is None or segment.power < 0:
                            raise ValueError("Manual segment needs nonnegative shaft power")
                        power, tail, bm, tm, lift_requested = segment.power, 0., 1., 1., 0.
                    else:
                        climb = segment.climb_rate
                        if segment.kind == "transition" and segment.end_altitude is not None:
                            climb = (segment.end_altitude - segment.altitude) / actual_duration
                        moment_now = (mass * .3 * chord - used_fuel * .35 * chord) if study.workflow == "requirements" else (
                            hw["moment"] + (empty + p["payload"]) * .3 * chord + (fuel_capacity - used_fuel) * hw["fuel_position"])
                        power, tail, bm, tm, lift_requested = shaft_power(m, v, h, climb, segment.kind, fraction, acceleration, moment_now / m)
                    peak = max(peak, power)
                    main_requested = power - lift_requested
                    peak_main, peak_lift = max(peak_main, main_requested), max(peak_lift, lift_requested)
                    tail_peak = max(tail_peak, tail)
                    blade_margin, tip_margin = min(blade_margin, bm), min(tip_margin, tm)
                    limit = available_power
                    if study.workflow == "hardware" and hw.get("power_map") and v > 0:
                        limit = min(limit, interpolate(hw["power_map"], v))
                    min_power_margin = min(min_power_margin, limit - main_requested)
                    if fuelled:
                        flow = interpolate(hw["engine_map"], main_requested) if hw["engine_map"] else main_requested * a["fuel_sfc"]
                        if flow < 0:
                            raise ValueError("Engine fuel-flow map returned negative consumption")
                        used_fuel += flow * dt
                        electric = 0.
                        current, voltage = 0., hw["voltage"]
                    if not fuelled or family == "lift_cruise":
                        electric = (lift_requested if fuelled else power) / a["motor_efficiency"] + a["avionics_power"]
                        if drive_state:
                            electric = drive_state["bus_power"] + lift_requested / a["motor_efficiency"] + a["avionics_power"]
                        soc = 1 - energy / max(energy_capacity, 1.)
                        # Empty conceptual initial guesses are corrected by sizing;
                        # hardware exhaustion remains a feasibility residual.
                        ocv = hw["voltage"] * (.85 + .15 * max(0., soc))
                        if hw.get("ocv_map"):
                            ocv = interpolate(hw["ocv_map"], soc)
                        resistance = interpolate(hw["resistance_map"], soc) if hw.get("resistance_map") else hw["resistance"]
                        current, voltage = battery_operating_point(electric, ocv, resistance)
                        energy += (electric + current * current * resistance) * dt
                        peak_current, min_voltage = max(peak_current, current), min(min_voltage, voltage)
                    if segment.kind == "transition":
                        transition_energy += (power if fuelled else electric) * dt
                    stall = math.sqrt(2 * m * G / (atmosphere(h).density * p["wing_area"] * a["cl_max"])) if winged else 0.
                    if winged and segment.kind in ("cruise", "climb", "descent"):
                        min_stall_margin = min(min_stall_margin, v - stall)
                    elapsed += dt
                    moment = (mass * .3 * chord - used_fuel * .35 * chord) if study.workflow == "requirements" else (
                        hw["moment"] + (empty + p["payload"]) * .3 * chord + (fuel_capacity - used_fuel) * hw["fuel_position"])
                    end_mass = mass - used_fuel
                    if end_mass <= 0:
                        raise ValueError("Mission consumed more fuel than vehicle mass")
                    history.append(dict(segment=segment.name, time=elapsed, speed=v, altitude=h,
                                        mass=end_mass, power=power, current=current, voltage=voltage,
                                        energy=energy, fuel_used=used_fuel, stall_speed=stall,
                                        cg=moment / end_mass))
                    if family == "helicopter":
                        history[-1].update(rotor_state)
                    if segment.kind == "transition":
                        history[-1].update(transition_state)
                    if drive_state:
                        history[-1].update({"drive_" + k: v for k, v in drive_state.items()})
                        history[-1]["drive_voltage_margin"] = (voltage - drive_state["motor_voltage"]) / voltage
            if sizing:
                available_power = peak_main * p.get("power_margin", a["power_margin"])
                available_lift_power = peak_lift * p.get("power_margin", a["power_margin"])
                propulsion_mass = (available_power + available_lift_power) * a["power_specific_mass"]
                if fuelled:
                    fuel_capacity = used_fuel / (1 - reserve) * p.get("storage_margin", 1.)
                    storage_mass = fuel_capacity * 1.12
                else:
                    energy_capacity = energy / ((1 - reserve) * a["usable_fraction"]) * p.get("storage_margin", 1.)
                    storage_mass = energy_capacity / a["specific_energy"]
                if fuelled and family == "lift_cruise":
                    energy_capacity = energy / ((1 - reserve) * a["usable_fraction"]) * p.get("storage_margin", 1.)
                    storage_mass += energy_capacity / a["specific_energy"]
                new_mass = p["payload"] + empty + propulsion_mass + storage_mass
            elif study.workflow == "requirements":
                propulsion_mass = (available_power + available_lift_power) * a["power_specific_mass"]
                storage_mass = fuel_capacity * 1.12 if fuelled else energy_capacity / a["specific_energy"]
                if fuelled and family == "lift_cruise":
                    storage_mass += energy_capacity / a["specific_energy"]
                new_mass = p["payload"] + empty + propulsion_mass + storage_mass
            else:
                propulsion_mass = hw["mass"] - hw["battery_mass"]
                storage_mass = hw["battery_mass"] + (fuel_capacity if fuelled else 0.)
                new_mass = p["payload"] + empty + propulsion_mass + storage_mass
            residual = new_mass - mass
            if new_mass > a["max_mass"] or not math.isfinite(new_mass):
                raise ValueError("Mass/energy sizing diverged beyond technology limit")
            if abs(residual) <= a["closure_tolerance"] * max(1., mass):
                break
            mass += .5 * residual
        else:
            raise ValueError("Mass/mission closure failed after 120 iterations")
        duration = base_duration * duration_scale
        energy_available = (fuel_capacity - used_fuel / (1 - reserve)) if fuelled else energy_capacity * a["usable_fraction"] - energy / (1 - reserve)
        endurance = duration * ((fuel_capacity * (1 - reserve) / used_fuel) if fuelled and used_fuel else
                                energy_capacity * a["usable_fraction"] * (1 - reserve) / max(energy, 1e-9))
        if fuelled and family == "lift_cruise":
            endurance = min(endurance, duration * energy_capacity * a["usable_fraction"] * (1 - reserve) / max(energy, 1e-9))
        rho = atmosphere(study.mission.segments[0].altitude).density
        stall = math.sqrt(2 * mass * G / (rho * p["wing_area"] * a["cl_max"])) if winged else 0.
        cg = history[0]["cg"]
        neutral = .25 * chord + .7 * p["tail_area"] * p["tail_arm"] / p["wing_area"]
        sm = (neutral - max(row["cg"] for row in history)) / chord if winged else 0.
        clearance = 2 * p["arm_length"] * math.sin(math.pi / disks) - p["rotor_diameter"] if disks > 1 else p["tail_rotor_arm"] - p["rotor_diameter"] / 2 - p["tail_rotor_diameter"] / 2
        metrics = dict(takeoff_mass=mass, payload=p["payload"], endurance=endurance,
                       range=endurance * p["cruise_speed"], stall_speed=stall,
                       cruise_speed=p["cruise_speed"], installed_power=available_power + available_lift_power,
                       cruise_installed_power=available_power, installed_lift_power=available_lift_power,
                       peak_power=peak, peak_current=peak_current, min_voltage=min_voltage,
                       energy_required=energy, energy_available=energy_available if not fuelled else 0.,
                       fuel_used=used_fuel, structural_margin=structural_margin, static_margin=sm, cg=cg,
                       climb_rate=max(0., available_power - peak_main) * a["efficiency"] / (mass * G),
                       rotor_clearance=clearance, tail_rotor_power=tail_peak,
                       transition_energy=transition_energy, mass_closure=abs(residual),
                       energy_capacity=energy_capacity, fuel_capacity=fuel_capacity)
        # Constant excess-power acceleration approximation; clearly identified in docs.
        metrics["takeoff_distance"] = (1.2 * stall) ** 2 / (2 * max(.1, available_power * a["efficiency"] / max(1., 1.2 * stall) / mass - .04 * G)) if winged else 0.
        margins = dict(energy=energy_available / max(fuel_capacity if fuelled else energy_capacity, 1e-9),
                       power=(available_power - peak_main) / max(available_power, 1.),
                       blade_lift=blade_margin, tip_mach=tip_margin)
        if study.workflow == "hardware" and math.isfinite(min_power_margin):
            margins["operating_power_map"] = min_power_margin / max(available_power, 1.)
        if family == "lift_cruise":
            margins["lift_power"] = (available_lift_power - peak_lift) / max(available_lift_power, 1.)
            margins["lift_energy"] = (energy_capacity * a["usable_fraction"] - energy / (1 - reserve)) / max(energy_capacity, 1.)
            tilt_limit = a.get("transition_tilt_limit", math.radians(20.))
            if not 0 <= tilt_limit < math.pi / 2:
                raise ValueError("Transition lift-system tilt limit must be in [0, pi/2) radians")
            margins["transition_tilt"] = tilt_limit - max((row.get("lift_tilt", 0.) for row in history), default=0.)
        if not fuelled or family == "lift_cruise":
            margins.update(current=(hw["max_current"] - peak_current) / hw["max_current"],
                           voltage=(min_voltage - hw["min_voltage"]) / hw["min_voltage"])
        if winged:
            margins["static_margin"] = sm - .05
            margins["structure"] = structural_margin
            if math.isfinite(min_stall_margin):
                margins["stall"] = min_stall_margin / max(stall, 1.)
        if family != "fixed_wing":
            margins["clearance"] = clearance / p["rotor_diameter"]
            margins["structure"] = structural_margin
        if "drive" in hw or "motor_drive" in hw:
            for key in ("motor_current_margin", "controller_current_margin", "motor_power_margin", "motor_rpm_margin", "voltage_margin"):
                margins["drive_" + key] = min((row["drive_" + key] for row in history if "drive_" + key in row), default=1.)
        warnings = ["Conceptual model; empirical mass/drag assumptions require calibration."]
        if family == "helicopter":
            warnings.append("Helicopter airframe mass is an empirical fraction of takeoff mass. Mast, skid and fuselage stresses are not checked.")
        if any(s.kind == "manual" for s in study.mission.segments):
            warnings.append("Manual power budget is an explicit approximation, not a flight-condition power prediction.")
        if study.workflow == "hardware" and not fuelled and "drive" not in hw and "motor_drive" not in hw:
            warnings.append("Electrical conversion uses the declared constant motor efficiency; motor terminal operating points are not established by a power rating alone.")
        if family == "helicopter":
            warnings.append("Rigid-rotor steady force/moment trim with uniform inflow; articulated flapping, descent/vortex-ring operation and dynamic stability are outside this model.")
        if family == "lift_cruise":
            warnings.append("Prescribed planar transition balances forces; braking requires lift-system tilt. Moment trim, rotor-wing interference and controllability remain unverified.")
        p.update(installed_power=available_power + available_lift_power,
                 energy_capacity=energy_capacity, fuel_mass=fuel_capacity,
                 _sized_cap_area=cap_area, _sized_airframe_mass=empty)
        result = EvaluationResult(design=p, metrics=metrics, margins=margins,
                                mass_breakdown=dict(payload=p["payload"], airframe=empty,
                                                    propulsion=propulsion_mass, storage=storage_mass),
                                mission_history=history, warnings=warnings, valid=True,
                                converged=True, closure_residual=abs(residual))
        if not p.get("_endurance_probe"):
            _mission_endurance(self, study, p, result)
        return result


def _mission_endurance(model, study, parameters, result):
    """Resimulate one endurance segment with installed sizes held fixed.

    The longest cruise/hover segment is extended; takeoff, transition and landing
    stay fixed. The first intrinsic mission limit, including reserve, bounds time.
    This does not optimize the mission schedule or silently resize the aircraft.
    """
    candidates = [(segment.duration, i) for i, segment in enumerate(study.mission.segments)
                  if segment.kind in ("cruise", "hover", "manual")]
    if not candidates:
        result.warnings.append("Endurance/range unavailable: mission needs a cruise, hover or explicitly approximate manual-power segment.")
        result.metrics.pop("endurance", None)
        result.metrics.pop("range", None)
        return
    _, index = max(candidates)
    alternate = deepcopy(study)
    original_total = sum(s.duration for s in alternate.mission.segments)
    scale = parameters.get("mission_duration", original_total) / original_total
    for segment in alternate.mission.segments:
        segment.duration *= scale
    probe = dict(parameters)
    probe.pop("mission_duration", None)
    probe.update(_endurance_probe=1., _fixed_takeoff_mass=result.metrics["takeoff_mass"],
                 _fixed_power=result.metrics["cruise_installed_power"], _fixed_lift_power=result.metrics["installed_lift_power"],
                 _fixed_energy=result.metrics["energy_capacity"], _fixed_fuel=result.metrics["fuel_capacity"],
                 _fixed_cap_area=parameters["_sized_cap_area"], _fixed_airframe_mass=parameters["_sized_airframe_mass"])
    trial_error = ""
    trial_margins = {}
    def trial(duration):
        nonlocal trial_error, trial_margins
        trial_error, trial_margins = "", {}
        alternate.mission.segments[index].duration = duration
        try:
            answer = model.evaluate(alternate, dict(probe))
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            trial_error = str(exc)
            return None
        trial_margins = answer.margins
        return answer if answer.valid and all(m >= -1e-8 for m in answer.margins.values()) else None

    lo = 1e-6
    best = trial(lo)
    if best is None:
        if trial_error:
            raise ValueError("Endurance mission is outside model validity: " + trial_error)
        result.metrics.update(endurance=0., range=0.)
        result.warnings.append("No feasible endurance with the fixed takeoff/transition/landing overhead and installed limits.")
        return
    hi = max(1., study.mission.segments[index].duration * scale)
    bound = study.vehicle.assumptions.get("endurance_time_limit", 86400.)
    if not 1 <= bound <= 604800:
        raise ValueError("Endurance search time limit must be between one second and seven days")
    hi = min(hi, bound)
    while True:
        candidate = trial(hi)
        if candidate is None:
            upper_error, upper_margins = trial_error, trial_margins
            break
        lo, best = hi, candidate
        if hi >= bound:
            raise ValueError("Endurance limit not found within declared endurance_time_limit")
        hi = min(2 * hi, bound)
    while hi - lo > max(.05, 1e-5 * hi):
        mid = (lo + hi) / 2
        candidate = trial(mid)
        if candidate is None:
            hi = mid
            upper_error, upper_margins = trial_error, trial_margins
        else:
            lo, best = mid, candidate
    if upper_error:
        raise ValueError("Endurance limit is outside model validity: " + upper_error)
    result.metrics["endurance"] = best.mission_history[-1]["time"]
    result.metrics["range"] = _mission_distance(best.mission_history)
    result.endurance_history = best.mission_history
    result.endurance_limit = ", ".join(key for key, value in upper_margins.items() if value < -1e-8)
    result.warnings.append("Endurance resimulates segment '" + study.mission.segments[index].name +
                           "' with installed sizes and all other segment durations fixed; reserve and intrinsic limits enforced.")


def _mission_distance(history):
    elapsed, distance = 0., 0.
    for row in history:
        distance += row["speed"] * (row["time"] - elapsed)
        elapsed = row["time"]
    return distance


for _family in ("fixed_wing", "multirotor", "helicopter", "lift_cruise"):
    register_model(_family, AircraftModel())
