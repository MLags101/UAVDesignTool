"""Shared inputs for the supersonic jet tools.

Every jet tool describes the aircraft the same way, so a value typed into one
form means the same thing in the next. Defaults describe a representative
100 kg-class Mach 1.6-2 jet UAV.
"""

from . import units
from .airbreathing import Turbojet
from .supersonic import Configuration

GEOMETRY_INPUTS = [
    {"key": "wing_area", "label": "Wing Reference Area", "unit": "m^2", "type": "number",
     "default": "1.2"},
    {"key": "aspect_ratio", "label": "Wing Aspect Ratio", "type": "number", "default": "2.5",
     "help": "Supersonic wings are low aspect ratio: 2-3.5 typical."},
    {"key": "le_sweep", "label": "Leading-Edge Sweep", "unit": "deg", "type": "number",
     "default": "45", "help": "Sweep behind the Mach cone (subsonic leading edge) "
                              "cuts wave drag due to lift."},
    {"key": "taper", "label": "Taper Ratio", "type": "number", "default": "0.25"},
    {"key": "thickness_ratio", "label": "Wing Thickness Ratio (t/c)", "type": "number",
     "default": "0.04", "help": "Wave drag grows with (t/c)^2; 3-5% is usual."},
    {"key": "body_length", "label": "Fuselage Length", "unit": "m", "type": "number",
     "default": "3.5"},
    {"key": "body_diameter", "label": "Fuselage Diameter", "unit": "m", "type": "number",
     "default": "0.3"},
    {"key": "htail_area", "label": "Horizontal Tail Area", "unit": "m^2", "type": "number",
     "default": "0.25", "help": "0 for a tailless delta."},
    {"key": "vtail_area", "label": "Vertical Tail Area", "unit": "m^2", "type": "number",
     "default": "0.18"},
    {"key": "tail_arm", "label": "Tail Arm (wing to tail MAC quarter chords)", "unit": "m",
     "type": "number", "default": "1.2"},
    {"key": "inlet_capture_area", "label": "Inlet Capture Area", "unit": "m^2",
     "type": "number", "default": "0.012", "help": "Size it with the Inlet Design tool."},
    {"key": "e_wd", "label": "Wave Drag Efficiency E_WD", "type": "number", "default": "1.8",
     "help": "Multiple of Sears-Haack drag: 1.2 well area-ruled, 1.8-2.2 typical, 2.5+ poor."},
    {"key": "cd_misc", "label": "Miscellaneous CD0", "type": "number", "default": "0.002",
     "help": "Antennas, gaps, inlet spillage, protuberances."},
]

ENGINE_INPUTS = [
    {"key": "sls_thrust", "label": "Sea-Level Static Thrust (dry)", "unit": "N",
     "type": "number", "default": "1500"},
    {"key": "pressure_ratio", "label": "Compressor Pressure Ratio", "type": "number",
     "default": "4.5", "help": "Small turbojets 3-6; larger engines 8-25."},
    {"key": "tt4_max", "label": "Max Turbine Inlet Temperature", "unit": "K",
     "type": "number", "default": "1150", "help": "Uncooled small turbines 1050-1250 K."},
    {"key": "afterburner", "label": "Afterburner", "type": "choice",
     "choices": ["Yes", "No"], "default": "Yes"},
    {"key": "tt7_max", "label": "Afterburner Exit Temperature", "unit": "K",
     "type": "number", "default": "1800"},
    {"key": "throttle_ratio", "label": "Throttle Ratio (TR)", "type": "number",
     "default": "1.05", "help": "1.0 matches the engine to sea-level static; 1.05-1.15 "
                                "holds thrust at high Mach."},
    {"key": "inlet", "label": "Inlet", "type": "choice",
     "choices": ["Single ramp", "Double ramp", "Pitot (normal shock)", "MIL-E-5007D"],
     "default": "Single ramp"},
    {"key": "nozzle", "label": "Nozzle", "type": "choice",
     "choices": ["Convergent-divergent", "Convergent"], "default": "Convergent-divergent"},
]

MASS_INPUTS = [
    {"key": "mass", "label": "Aircraft Mass", "unit": "kg", "type": "number", "default": "105"},
    {"key": "cl_max", "label": "Max Lift Coefficient", "type": "number", "default": "1.0",
     "help": "Thin swept wings without flaps: 0.8-1.1."},
]

_INLETS = {"Single ramp": ("ramp", 1), "Double ramp": ("ramp", 2),
           "Pitot (normal shock)": ("pitot", 1), "MIL-E-5007D": ("mil", 1)}


def yes(inputs, key, default="Yes"):
    return str(inputs.get(key) or default).strip().lower() in ("yes", "y", "true", "1", "on")


def configuration(inputs):
    p = units.positive
    return Configuration(
        wing_area=p(inputs, "wing_area", "m^2", "Wing area", 1.2),
        aspect_ratio=p(inputs, "aspect_ratio", "", "Aspect ratio", 2.5),
        le_sweep_deg=units.optional(inputs, "le_sweep", "deg", 45.0),
        taper=units.optional(inputs, "taper", "", 0.25),
        thickness_ratio=p(inputs, "thickness_ratio", "", "Thickness ratio", 0.04),
        body_length=p(inputs, "body_length", "m", "Fuselage length", 3.5),
        body_diameter=p(inputs, "body_diameter", "m", "Fuselage diameter", 0.3),
        htail_area=units.optional(inputs, "htail_area", "m^2", 0.25),
        vtail_area=units.optional(inputs, "vtail_area", "m^2", 0.18),
        tail_arm=p(inputs, "tail_arm", "m", "Tail arm", 1.2),
        inlet_capture_area=units.optional(inputs, "inlet_capture_area", "m^2", 0.012),
        e_wd=p(inputs, "e_wd", "", "E_WD", 1.8),
        cd_misc=units.optional(inputs, "cd_misc", "", 0.002),
    )


def engine(inputs):
    kind, ramps = _INLETS.get(str(inputs.get("inlet") or "Single ramp"), ("ramp", 1))
    return Turbojet(
        sls_thrust=units.positive(inputs, "sls_thrust", "N", "Static thrust", 1500.0),
        pressure_ratio=units.positive(inputs, "pressure_ratio", "", "Pressure ratio", 4.5),
        tt4_max=units.positive(inputs, "tt4_max", "K", "Turbine inlet temperature", 1150.0),
        afterburner=yes(inputs, "afterburner"),
        tt7_max=units.positive(inputs, "tt7_max", "K", "Afterburner temperature", 1800.0),
        throttle_ratio=units.positive(inputs, "throttle_ratio", "", "Throttle ratio", 1.05),
        inlet=kind, inlet_ramps=ramps,
        nozzle="convergent" if str(inputs.get("nozzle") or "").startswith("Convergent") and
               not str(inputs.get("nozzle")).startswith("Convergent-") else "ideal",
    )
