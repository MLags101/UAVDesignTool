"""Headless aerospace study API; numerical backends are imported lazily."""
from .schema import (
    ComponentDefinition, VehicleDefinition, MissionDefinition, MissionSegment,
    DesignVariable, Requirement, Objective, OperatingScenario, StudyDefinition,
    EvaluationResult, OptimizationResult, StudyResult,
)
from .engine import evaluate, optimize, sweep, assess_uncertainty, sensitivity
from .templates import template

__all__ = [name for name in globals() if not name.startswith("_")]
