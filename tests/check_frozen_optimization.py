"""Manual release gate: python tests/check_frozen_optimization.py path/to/app.exe."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uavlib.optimization import template, Objective
from uavlib.optimization.storage import atomic_json


def main():
    exe = Path(sys.argv[1]).resolve()
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(key, None)
    env["PATH"] = os.environ.get("SystemRoot", "C:\\Windows") + "\\System32"
    env["QT_QPA_PLATFORM"] = "offscreen"
    for mode in ("evaluate", "single", "pareto", "cancel"):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            study = template()
            study.max_evaluations = 35 if mode != "cancel" else 100000
            if mode == "pareto":
                study.objectives.append(Objective("installed_power", scale=100))
            atomic_json(folder / "request.json", {"study": study.to_dict(), "mode": "evaluate" if mode == "evaluate" else "optimize"})
            process = subprocess.Popen([str(exe), "--optimization-worker", str(folder)], env=env,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            if mode == "cancel":
                deadline = time.monotonic() + 60
                while not (folder / "progress.jsonl").exists() and time.monotonic() < deadline:
                    time.sleep(.1)
                (folder / "cancel").touch()
            try:
                code = process.wait(timeout=90)
            except subprocess.TimeoutExpired:
                process.kill()
                raise
            if not (folder / "result.json").exists():
                raise RuntimeError(f"Frozen {mode} failed with exit code {code}")
            result = json.loads((folder / "result.json").read_text())
            assert result["ok"], result
            if mode == "cancel":
                assert result["result"]["status"] == "cancelled", result
            elif mode == "evaluate":
                assert result["result"]["valid"], result
            else:
                assert result["result"]["candidates"], result
            print("PASS", mode, flush=True)


if __name__ == "__main__":
    main()
