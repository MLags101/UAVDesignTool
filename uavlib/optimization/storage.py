"""Portable, atomic study files and immutable run snapshots."""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import os
import shutil
import uuid
from .schema import StudyDefinition, MODEL_VERSION


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def project_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Study path must remain within the project")
    return path


class StudyStore:
    def __init__(self, project_dir):
        self.root = Path(project_dir).resolve()

    def save_study(self, study, relative=None):
        study.validate()
        relative = relative or f"Optimization/studies/{uuid.uuid4().hex}.json"
        atomic_json(project_path(self.root, relative), study.to_dict())
        return relative

    def load_study(self, relative):
        return StudyDefinition.from_dict(json.loads(project_path(self.root, relative).read_text(encoding="utf-8")))

    def save_run(self, study, result):
        relative = f"Optimization/runs/{uuid.uuid4().hex}"
        folder = project_path(self.root, relative)
        folder.mkdir(parents=True, exist_ok=False)
        atomic_json(folder / "study.json", study.to_dict())
        atomic_json(folder / "result.json", result.to_dict())
        atomic_json(folder / "manifest.json", {"created": datetime.now(timezone.utc).isoformat(),
                    "input_hash": study.fingerprint(), "model_version": MODEL_VERSION})
        return relative

    def import_data(self, source):
        source = Path(source)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        relative = f"Optimization/data/{digest[:16]}-{source.name}"
        target = project_path(self.root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source, target)
        return relative, digest

    def stale(self, study, result):
        if result.get("input_hash") != study.fingerprint():
            return True
        for relative, digest in study.source_hashes.items():
            path = project_path(self.root, relative)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                return True
        return False


def export_study(study, directory, result=None):
    """Export a study plus a runnable script; uavlib is a required installed/source dependency."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(directory / "study.json", study.to_dict())
    (directory / "run_study.py").write_text(
        '"""Run with the same uavlib version and pinned numerical dependencies."""\n'
        'import json\nfrom pathlib import Path\n'
        'from uavlib.optimization import StudyDefinition, optimize\n'
        'from uavlib.optimization.storage import atomic_json\n'
        'root = Path(__file__).resolve().parent\n'
        'study = StudyDefinition.from_dict(json.loads((root / "study.json").read_text()))\n'
        'result = optimize(study)\natomic_json(root / "result.json", result.to_dict())\n', encoding="utf-8")
    if result:
        data = result.to_dict() if hasattr(result, "to_dict") else result
        atomic_json(directory / "result.json", data)
        rows = data.get("candidates", data.get("evaluations", []))
        if isinstance(rows, list) and rows:
            keys = sorted({key for r in rows for key in r.get("metrics", {})})
            with (directory / "candidates.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["candidate", "valid", "feasible"] + keys)
                writer.writeheader()
                for i, r in enumerate(rows):
                    writer.writerow({"candidate": i, "valid": r["valid"], "feasible": r["feasible"], **r["metrics"]})
