"""Editable assumptions, never represented as manufacturer measurements."""
from .schema import *

PARAMETERS = {
    "payload": ("kg", "mass"), "wing_area": ("m^2", "area"),
    "mission_duration": ("s", "time"),
    "storage_margin": ("", "dimensionless"), "power_margin": ("", "dimensionless"),
    "structure_margin": ("", "dimensionless"),
    "aspect_ratio": ("", "dimensionless"), "tail_area": ("m^2", "area"),
    "tail_arm": ("m", "length"), "rotor_diameter": ("m", "length"),
    "rotor_rpm": ("rpm", "angular_speed"), "blade_chord": ("m", "length"),
    "blade_count": ("", "count"), "tail_rotor_diameter": ("m", "length"),
    "tail_rotor_arm": ("m", "length"), "arm_length": ("m", "length"),
    "main_rotor_x": ("m", "length"), "main_rotor_height": ("m", "length"), "tail_rotor_height": ("m", "length"),
    "arm_diameter": ("m", "length"), "arm_wall": ("m", "length"),
    "cruise_speed": ("m/s", "speed"), "installed_power": ("W", "power"),
    "energy_capacity": ("J", "energy"), "fuel_mass": ("kg", "mass"),
    "body_length": ("m", "length"), "body_diameter": ("m", "length"),
    "fin_area": ("m^2", "area"), "fin_span": ("m", "length"),
    "propellant_mass": ("kg", "mass"), "burn_time": ("s", "time"),
    "recovery_area": ("m^2", "area"),
    "launch_altitude": ("m", "length"),
}
METRICS = {
    "takeoff_mass": "kg", "payload": "kg", "endurance": "s", "range": "m",
    "stall_speed": "m/s", "climb_rate": "m/s", "static_margin": "",
    "cg": "m", "energy_required": "J", "energy_available": "J",
    "installed_power": "W", "peak_power": "W", "peak_current": "A",
    "min_voltage": "V", "fuel_used": "kg", "structural_margin": "",
    "rotor_clearance": "m", "takeoff_distance": "m", "cruise_speed": "m/s",
    "apogee": "m", "max_mach": "", "max_dynamic_pressure": "Pa",
    "max_acceleration": "m/s^2", "guide_exit_speed": "m/s", "landing_speed": "m/s",
    "tail_rotor_power": "W", "transition_energy": "J", "mass_closure": "kg",
    "energy_capacity": "J", "fuel_capacity": "kg",
    "cruise_installed_power": "W", "installed_lift_power": "W",
}

FAMILY_PARAMETERS = {
    "fixed_wing": ["payload", "wing_area", "aspect_ratio", "tail_area", "tail_arm", "cruise_speed"],
    "multirotor": ["payload", "rotor_diameter", "arm_length", "arm_diameter", "arm_wall", "cruise_speed"],
    "helicopter": ["payload", "rotor_diameter", "rotor_rpm", "blade_chord", "blade_count", "tail_rotor_diameter", "tail_rotor_arm", "main_rotor_x", "main_rotor_height", "tail_rotor_height", "cruise_speed"],
    "lift_cruise": ["payload", "wing_area", "aspect_ratio", "tail_area", "tail_arm", "cruise_speed", "rotor_diameter", "arm_length", "arm_diameter", "arm_wall"],
    "rocket": ["payload", "body_length", "body_diameter", "fin_area", "fin_span", "propellant_mass", "burn_time", "recovery_area", "launch_altitude"],
}


def template(family="fixed_wing", workflow="requirements", propulsion="electric"):
    if family not in ("fixed_wing", "multirotor", "helicopter", "lift_cruise", "rocket"):
        raise ValueError("Unknown vehicle family")
    p = dict(payload=.5, wing_area=.7, aspect_ratio=8., tail_area=.14, tail_arm=.8,
             storage_margin=1.05, power_margin=1.2, structure_margin=1.1,
             main_rotor_x=.08874119674649424, main_rotor_height=.15, tail_rotor_height=.15,
             rotor_diameter=.5, rotor_rpm=4000., blade_chord=.035, blade_count=2.,
             tail_rotor_diameter=.22, tail_rotor_arm=.8, arm_length=.5, cruise_speed=18.,
             arm_diameter=.025, arm_wall=.0015,
             installed_power=1500., energy_capacity=400000., fuel_mass=.4,
             body_length=1.2, body_diameter=.08, fin_area=.012, fin_span=.10,
             propellant_mass=.15, burn_time=2., recovery_area=.6, launch_altitude=0.)
    a = dict(cd0=.035, oswald=.8, cl_max=1.2, efficiency=.75, motor_efficiency=.88,
             figure_of_merit=.65, wing_areal_mass=1.2, fixed_mass=.4,
             power_specific_mass=.0004, specific_energy=720000., fuel_sfc=9e-8,
             load_factor=3.8, material_density=1600., modulus=70e9,
             allowable_stress=250e6, spar_depth_fraction=.08, deflection_fraction=.08,
             flat_plate_area=.035, usable_fraction=.8, voltage=22.2, resistance=.03,
             max_current=100., min_voltage=18., avionics_power=8., tail_efficiency=.7,
             rotor_profile_cd=.012, max_blade_cl=1.2, tip_mach_limit=.65,
             transmission_efficiency=.92, power_margin=1.2, closure_tolerance=1e-6,
             transition_tilt_limit=.3490658503988659,
             max_mass=1000., skin_areal_mass=2., rocket_cd=.45, rocket_max_mach=.8,
             specific_impulse=170., motor_inert_fraction=.35, guide_length=2.,
             parachute_cd=1.5, max_q=50000., max_acceleration=200.,
             max_landing_speed=8., max_time=1200., step=.1)
    segments = [MissionSegment("Cruise", "cruise", 600, 18)]
    names = ["wing_area", "aspect_ratio", "tail_area", "cruise_speed"]
    if family in ("multirotor", "helicopter"):
        segments = [MissionSegment("Hover", "hover", 300, 0)]
        names = ["rotor_diameter", "blade_chord"] if family == "helicopter" else ["rotor_diameter", "arm_length", "arm_diameter", "arm_wall"]
        if family == "helicopter":
            p.update(rotor_diameter=1.6, rotor_rpm=1300., blade_chord=.06, tail_rotor_arm=1.1)
    if family == "lift_cruise":
        segments = [MissionSegment("Vertical takeoff", "hover", 30, 0),
                    MissionSegment("Transition out", "transition", 15, 0, end_speed=18),
                    MissionSegment("Cruise", "cruise", 600, 18),
                    MissionSegment("Transition in", "transition", 15, 18, end_speed=0),
                    MissionSegment("Landing", "hover", 30, 0)]
        names += ["rotor_diameter", "arm_length", "arm_diameter", "arm_wall"]
    if family == "rocket":
        p.update(payload=.1)
        names = ["body_diameter", "fin_area", "recovery_area"]
        segments = []
    variables = [DesignVariable(k, p[k], p[k] * .6, p[k] * 1.6,
                                PARAMETERS[k][0], max(p[k], .01)) for k in names]
    if workflow == "requirements" and family != "rocket":
        variables += [DesignVariable("storage_margin", p["storage_margin"], 1., 2.),
                      DesignVariable("power_margin", p["power_margin"], 1.05, 2.5)]
        if family in ("fixed_wing", "lift_cruise"):
            variables += [DesignVariable("structure_margin", p["structure_margin"], 1., 2.)]
    requirements = [Requirement("energy_available", 0)] if family != "rocket" else [Requirement("guide_exit_speed", 12, scale=12)]
    study = StudyDefinition(name=f"{family.replace('_', ' ').title()} {workflow}", workflow=workflow,
                            vehicle=VehicleDefinition(family, propulsion, p, a),
                            mission=MissionDefinition(segments), variables=variables,
                            requirements=requirements,
                            objectives=[Objective("takeoff_mass" if workflow == "requirements" else
                                                  ("apogee" if family == "rocket" else "endurance"),
                                                  "min" if workflow == "requirements" else "max")])
    if family == "rocket":
        study.requirements.append(Requirement("apogee", 150., scale=150))
    # Hardware starts deliberately empty. A sample technology estimate must not
    # silently become a measured, fixed assembly.
    return study
