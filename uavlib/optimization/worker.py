"""File-backed process protocol, usable from Python and the frozen application."""
import argparse
import json
import os
from pathlib import Path
import traceback
from .schema import StudyDefinition, MODEL_VERSION
from .engine import optimize, evaluate, sweep, assess_uncertainty, sensitivity
from .storage import atomic_json


def recover(folder):
    """Read a stopped worker's durable evaluations without rerunning physics.

    Call only after the worker exits. A truncated final journal record is ignored;
    corruption in any completed record is an error, never silently discarded.
    """
    from .schema import EvaluationResult, OptimizationResult, StudyResult
    from .engine import nondominated
    folder = Path(folder)
    if (folder / "result.json").exists():
        return json.loads((folder / "result.json").read_text(encoding="utf-8"))
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    study = StudyDefinition.from_dict(request["study"])
    metadata = json.loads((folder / "execution.json").read_text(encoding="utf-8"))
    if metadata["model_version"] != MODEL_VERSION or metadata["input_hash"] != study.fingerprint():
        raise ValueError("Recovery needs the original model version and unchanged request; journal retained")
    evaluations = []
    journal = folder / "evaluations.jsonl"
    if journal.exists():
        for line in journal.read_bytes().splitlines(keepends=True):
            if not line.endswith(b"\n"):
                break
            evaluations.append(EvaluationResult(**json.loads(line)))
    if not evaluations:
        return {"ok": False, "error": "No completed evaluations available for recovery"}
    mode = request.get("mode", "optimize")
    if mode == "optimize":
        result = OptimizationResult("interrupted", evaluations[0], nondominated(evaluations),
                                    evaluations=len(evaluations), input_hash=study.fingerprint(),
                                    provenance={"seed": study.seed, "recovered": True},
                                    solver_message="Worker interrupted; recovered completed evaluations only")
        result.history = [dict(evaluation=i + 1, design=r.design, valid=r.valid,
                               feasible=r.feasible, objectives=r.objectives, margins=r.margins,
                               errors=r.errors, metrics=r.metrics) for i, r in enumerate(evaluations)]
    elif mode == "evaluate":
        result = evaluations[0]
    else:
        result = StudyResult(mode, evaluations, {"recovered": True, "completed_samples": len(evaluations)},
                             study.seed, study.fingerprint(), "interrupted")
    response = {"ok": True, "result": result.to_dict()}
    atomic_json(folder / "result.json", response)
    return response


def execute(folder):
    folder = Path(folder)
    try:
        request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        study = StudyDefinition.from_dict(request["study"])
        mode = request.get("mode", "optimize")
        if (folder / "evaluations.jsonl").exists():
            raise ValueError("Worker request directory already contains evaluations; recover it or start a new run")
        atomic_json(folder / "execution.json", {"model_version": MODEL_VERSION, "input_hash": study.fingerprint()})

        def checkpoint(result):
            with (folder / "evaluations.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(result.to_dict(), allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

        def cancel():
            return (folder / "cancel").exists()

        def progress(row):
            with (folder / "progress.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
                stream.flush()

        if mode == "optimize":
            result = optimize(study, progress, cancel, checkpoint)
        elif mode == "evaluate":
            result = evaluate(study)
            checkpoint(result)
        elif mode == "sweep":
            result = sweep(study, request.get("specification", {}), progress, cancel, checkpoint)
        elif mode == "uncertainty":
            result = assess_uncertainty(study, request.get("design", {}), request["specification"], progress, cancel, checkpoint)
        elif mode == "sensitivity":
            result = sensitivity(study, request.get("design", {}), progress=progress, cancel=cancel, checkpoint=checkpoint)
        elif mode == "compare":
            from .adapters import compare
            from .schema import EvaluationResult
            answer = compare(request["backend"], study, EvaluationResult(**request["candidate"]), request["config"])
            atomic_json(folder / "result.json", {"ok": True, "result": answer})
            return 0
        else:
            raise ValueError(f"Unknown worker mode {mode}")
        atomic_json(folder / "result.json", {"ok": True, "result": result.to_dict()})
    except Exception as exc:
        atomic_json(folder / "result.json", {"ok": False, "error": str(exc), "traceback": traceback.format_exc()})
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    args = parser.parse_args()
    return execute(args.folder)


if __name__ == "__main__":
    raise SystemExit(main())
