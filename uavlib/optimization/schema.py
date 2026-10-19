"""Versioned study contracts. This module has no GUI or numerical dependencies."""
from dataclasses import asdict, dataclass, field
from typing import Any
import hashlib
import json
import math

MODEL_VERSION = "0.4.0-preview"


@dataclass
class ComponentDefinition:
    id: str
    kind: str
    mass: float
    quantity: int = 1
    position: float = 0.0
    properties: dict[str, Any] = field(default_factory=dict)
    source: str = "User supplied"
    conceptual: bool = False


@dataclass
class VehicleDefinition:
    family: str = "fixed_wing"
    propulsion: str = "electric"
    parameters: dict[str, float] = field(default_factory=dict)
    assumptions: dict[str, float] = field(default_factory=dict)
    components: list[ComponentDefinition] = field(default_factory=list)
    layout: str = "quad_x"


@dataclass
class MissionSegment:
    name: str = "Cruise"
    kind: str = "cruise"
    duration: float = 600.0
    speed: float = 18.0
    altitude: float = 0.0
    climb_rate: float = 0.0
    power: float | None = None
    end_speed: float | None = None
    end_altitude: float | None = None


@dataclass
class MissionDefinition:
    segments: list[MissionSegment] = field(default_factory=lambda: [MissionSegment()])
    reserve_fraction: float = 0.2


@dataclass
class DesignVariable:
    key: str
    initial: float
    lower: float
    upper: float
    unit: str = ""
    scale: float = 1.0
    free: bool = True
    integer: bool = False


@dataclass
class Requirement:
    metric: str
    limit: float
    sense: str = ">="
    scale: float = 1.0
    tolerance: float = 1e-6
    segment: str = ""


@dataclass
class Objective:
    metric: str = "takeoff_mass"
    sense: str = "min"
    scale: float = 1.0


@dataclass
class OperatingScenario:
    name: str
    altitude_offset: float = 0.0
    speed_factor: float = 1.0
    payload_delta: float = 0.0


@dataclass
class StudyDefinition:
    name: str = "Untitled study"
    workflow: str = "requirements"
    vehicle: VehicleDefinition = field(default_factory=VehicleDefinition)
    mission: MissionDefinition = field(default_factory=MissionDefinition)
    variables: list[DesignVariable] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    objectives: list[Objective] = field(default_factory=lambda: [Objective()])
    scenarios: list[OperatingScenario] = field(default_factory=list)
    robust: bool = False
    solver: str = "differential_evolution"
    seed: int = 42
    max_evaluations: int = 500
    # After a global search, polish continuous variables with integers held fixed.
    local_refinement: bool = False
    source_hashes: dict[str, str] = field(default_factory=dict)
    version: int = 1

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        d = dict(data)
        if d.get("version", 1) != 1:
            raise ValueError("Unsupported study schema version")
        v = dict(d.pop("vehicle", {}))
        v["components"] = [ComponentDefinition(**c) for c in v.get("components", [])]
        m = dict(d.pop("mission", {}))
        m["segments"] = [MissionSegment(**s) for s in m.get("segments", [])]
        for name, kind in (("variables", DesignVariable), ("requirements", Requirement),
                           ("objectives", Objective), ("scenarios", OperatingScenario)):
            if name in d:
                d[name] = [kind(**item) for item in d[name]]
        return cls(vehicle=VehicleDefinition(**v), mission=MissionDefinition(**m), **d)

    def fingerprint(self):
        payload = {"study": self.to_dict(), "model_version": MODEL_VERSION}
        def canonical(value):
            if isinstance(value, bool):
                return value
            if isinstance(value, (float, int)):
                return float(value)
            if isinstance(value, dict):
                return {k: canonical(v) for k, v in value.items()}
            if isinstance(value, list):
                return [canonical(v) for v in value]
            return value
        return hashlib.sha256(json.dumps(canonical(payload), sort_keys=True, allow_nan=False).encode()).hexdigest()

    def validate(self):
        if self.workflow not in ("requirements", "hardware"):
            raise ValueError("Workflow must be requirements or hardware")
        if not 1 <= len(self.objectives) <= 3:
            raise ValueError("Choose one to three objectives")
        if self.max_evaluations < 1:
            raise ValueError("Evaluation budget must be positive")
        if not 0 <= self.mission.reserve_fraction < 1:
            raise ValueError("Reserve fraction must be in [0, 1)")
        keys = [v.key for v in self.variables]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate design variable")
        for v in self.variables:
            if not all(math.isfinite(x) for x in (v.initial, v.lower, v.upper, v.scale)):
                raise ValueError(f"Nonfinite variable {v.key}")
            if not v.lower <= v.initial <= v.upper or v.scale <= 0:
                raise ValueError(f"Invalid bounds or scale for {v.key}")
            if v.integer and (v.initial != int(v.initial) or math.ceil(v.lower) > math.floor(v.upper)):
                raise ValueError(f"Invalid integer variable {v.key}")
        for r in self.requirements:
            if r.sense not in (">=", "<=", "==") or r.scale <= 0 or r.tolerance < 0:
                raise ValueError("Invalid requirement")
            if not all(math.isfinite(x) for x in (r.limit, r.scale, r.tolerance)):
                raise ValueError("Nonfinite requirement")
        for o in self.objectives:
            if o.sense not in ("min", "max") or not math.isfinite(o.scale) or o.scale <= 0:
                raise ValueError("Invalid objective")
        ids = [c.id for c in self.vehicle.components]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate component ID")
        for c in self.vehicle.components:
            if c.mass < 0 or not math.isfinite(c.mass) or c.quantity < 1 or int(c.quantity) != c.quantity:
                raise ValueError(f"Invalid component mass or quantity: {c.id}")
        for s in self.mission.segments:
            if s.duration <= 0 or s.speed < 0 or s.altitude < 0:
                raise ValueError(f"Invalid mission segment: {s.name}")
        if len({s.name for s in self.mission.segments}) != len(self.mission.segments):
            raise ValueError("Mission segment names must be unique")
        if len({s.name for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("Scenario names must be unique")
        for scenario in self.scenarios:
            if scenario.speed_factor <= 0:
                raise ValueError("Scenario speed factor must be positive")
        # JSON roundtrip also rejects NaN anywhere in maps or assumptions.
        json.dumps(self.to_dict(), allow_nan=False)


@dataclass
class EvaluationResult:
    design: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    margins: dict[str, float] = field(default_factory=dict)
    objectives: list[float] = field(default_factory=list)
    mass_breakdown: dict[str, float] = field(default_factory=dict)
    mission_history: list[dict[str, Any]] = field(default_factory=list)
    endurance_history: list[dict[str, Any]] = field(default_factory=list)
    endurance_limit: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    valid: bool = False
    feasible: bool = False
    converged: bool = False
    closure_residual: float = 0.0
    limiting_scenarios: dict[str, str] = field(default_factory=dict)
    sampled_inputs: dict[str, float] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class OptimizationResult:
    status: str
    baseline: EvaluationResult
    candidates: list[EvaluationResult] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    evaluations: int = 0
    input_hash: str = ""
    model_version: str = MODEL_VERSION
    solver_message: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class StudyResult:
    kind: str
    evaluations: list[EvaluationResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    seed: int = 42
    input_hash: str = ""
    status: str = "completed"

    def to_dict(self):
        return asdict(self)
