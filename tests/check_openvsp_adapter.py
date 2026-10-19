"""Run with Python matching the installed OpenVSP API; no GUI required.

python tests/check_openvsp_adapter.py path/to/OpenVSP-bin
This validates adapter execution, candidate geometry binding and output isolation.
It is not a complete-aircraft aerodynamic benchmark.
"""
from pathlib import Path
import hashlib
import math
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import openvsp as vsp
from uavlib.optimization import template, evaluate
from uavlib.optimization.adapters import compare
from uavlib.optimization.storage import atomic_json


def main():
    binary = Path(sys.argv[1]).resolve()
    output = Path("build/openvsp-validation/case").resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = output / "source.vsp3"
    study = template()
    candidate = evaluate(study)
    assert candidate.valid, candidate.errors
    vsp.ClearVSPModel()
    wing = vsp.AddGeom("WING")
    vsp.SetDriverGroup(wing, 1, vsp.AR_WSECT_DRIVER, vsp.AREA_WSECT_DRIVER, vsp.TAPER_WSECT_DRIVER)
    vsp.SetGeomName(wing, "Reference rectangular wing")
    for name, group, value in (("Taper", "XSec_1", 1.), ("Sweep", "XSec_1", 0.),
                               ("Camber", "XSecCurve_0", 0.), ("Camber", "XSecCurve_1", 0.)):
        parm = vsp.FindParm(wing, name, group)
        assert parm, (name, group)
        vsp.SetParmVal(parm, value)
    vsp.Update()
    bindings = {"wing_area": vsp.FindParm(wing, "TotalArea", "WingGeom"),
                "aspect_ratio": {"id": vsp.FindParm(wing, "Aspect", "XSec_1"), "scale": .5}}
    vsp.WriteVSPFile(str(source), vsp.SET_ALL)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    area, aspect = candidate.design["wing_area"], candidate.design["aspect_ratio"]
    config = dict(model_path=str(source), working_directory=str(output / "run"), vspaero_path=str(binary),
                  parameter_bindings=bindings,
                  geometry_integer_inputs={"GeomSet": [vsp.SET_NONE], "ThinGeomSet": [vsp.SET_ALL]},
                  integer_inputs={"GeomSet": [vsp.SET_NONE], "ThinGeomSet": [vsp.SET_ALL], "RefFlag": [0],
                                  "AlphaNpts": [1], "MachNpts": [1], "WakeNumIter": [5], "NCPU": [1]},
                  double_inputs={"Sref": [area], "bref": [math.sqrt(area * aspect)], "cref": [math.sqrt(area / aspect)],
                                 "AlphaStart": [5.], "AlphaEnd": [5.], "MachStart": [.05], "MachEnd": [.05], "Vinf": [18.]})
    atomic_json(output / "config.json", config)
    result = compare("openvsp", study, candidate, config)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before, "Source geometry changed"
    assert 0 < result["metrics"]["CL"] < 2, result
    assert result["metrics"]["CD"] > 0, result
    atomic_json(output / "result.json", result)
    print("PASS OpenVSP", result["version"], result["metrics"], flush=True)


if __name__ == "__main__":
    main()
