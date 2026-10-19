"""Offscreen integration: real widgets, editor roundtrip and process results."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from uav_app.models import ProjectModel
from uav_app.views import MainWindow
from uav_app.controllers import ProjectController


class TestWorkbenchGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.model = ProjectModel()
        self.model.create_project("Test", "Engineer", "", "", self.temp.name)
        self.view = MainWindow()
        self.controller = ProjectController(self.view, self.model)
        self.controller._setup_project_ui(is_loaded=True)
        self.workspace = self.controller.optimization_workspace

    def tearDown(self):
        self.workspace.shutdown()
        self.controller._dirty = False
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_template_selector_does_not_silently_change_family(self):
        self.workspace.family.setCurrentIndex(self.workspace.family.findData("helicopter"))
        with self.assertRaises(ValueError):
            self.workspace.read_editor()

    def test_workspace_roundtrip_and_save(self):
        self.assertEqual(self.view.central_stack.count(), 5)
        original = self.workspace.loaded.fingerprint()
        self.assertEqual(self.workspace.read_editor().fingerprint(), original)
        self.workspace.save_study()
        self.assertEqual(len(self.model.data.optimization["studies"]), 1)

    def test_mission_and_requirement_unit_suffixes(self):
        self.workspace.mission.item(0, 2).setText("10 min")
        self.workspace.mission.item(0, 3).setText("64.8 km/h")
        self.workspace.reserve.setText("20%")
        self.workspace.requirements.item(0, 1).setText("0 Wh")
        self.workspace.requirements.item(0, 3).setText("1 Wh")
        result = self.workspace.read_editor()
        self.assertEqual(result.mission.segments[0].duration, 600)
        self.assertAlmostEqual(result.mission.segments[0].speed, 18)
        self.assertEqual(result.mission.reserve_fraction, .2)
        self.assertEqual(result.requirements[0].scale, 3600)

    def test_baseline_worker(self):
        from PyQt6.QtTest import QTest
        self.workspace.start("evaluate")
        for _ in range(200):
            QTest.qWait(50)
            if not self.workspace.process:
                break
        self.assertIsNone(self.workspace.process)
        self.assertIsNotNone(self.workspace.result, self.workspace.log.toPlainText())
        self.assertTrue(self.workspace.result["candidates"][0]["valid"])
        self.assertEqual(len(self.model.data.optimization["runs"]), 1)

    def test_apply_resets_review_and_report_has_provenance(self):
        from uavlib.optimization import evaluate
        from uavlib.optimization.schema import OptimizationResult
        from uavlib.optimization.storage import StudyStore
        from uav_app.generator import generate_overleaf_zip
        from PyQt6.QtWidgets import QMessageBox
        from uav_app.optimization_view import put_rows
        study = self.workspace.read_editor()
        baseline = evaluate(study)
        run = OptimizationResult("evaluated", baseline, [baseline], input_hash=study.fingerprint())
        self.workspace.run_study = study
        self.workspace.result = run.to_dict()
        self.workspace.run_path = StudyStore(self.model.project_dir).save_run(study, run)
        put_rows(self.workspace.candidates, [[0, True, True, baseline.objectives, ""]])
        self.workspace.candidates.selectRow(0)
        self.workspace.stage.setCurrentText("Preliminary")
        stage = self.model.data.stages["Preliminary"]
        stage.review_state = stage.completed = True
        self.controller.view.stage_views["Preliminary"]["review_cb"].setChecked(True)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.workspace.apply_selected()
        self.assertFalse(stage.review_state)
        self.assertFalse(stage.completed)
        self.assertIn("Wing Area (S)", stage.parameters)
        self.assertEqual(len(self.model.data.optimization["applied"]), 1)
        path = generate_overleaf_zip(self.model, ["Preliminary"], {})
        with zipfile.ZipFile(path) as archive:
            text = archive.read("main.tex").decode()
            self.assertIn(study.fingerprint(), text)
            self.assertIn("Optimization studies", text)
            self.assertIn("Constraint margins", text)

    def test_open_saved_snapshot(self):
        from uavlib.optimization import evaluate
        from uavlib.optimization.schema import OptimizationResult
        study = self.workspace.read_editor()
        baseline = evaluate(study)
        run = OptimizationResult("evaluated", baseline, [baseline], input_hash=study.fingerprint())
        relative = self.workspace.store.save_run(study, run)
        self.model.data.optimization["runs"].append({"study": study.name, "path": relative, "status": "evaluated"})
        self.workspace.refresh_saved()
        self.workspace.open_run()
        self.assertEqual(self.workspace.run_path, relative)
        self.assertEqual(self.workspace.candidates.rowCount(), 1)

    def test_comparison_preserves_selected_core_result(self):
        import json
        from uavlib.optimization.storage import atomic_json
        core = {"candidates": [{"valid": True, "metrics": {"takeoff_mass": 3}}]}
        self.workspace.result = core
        self.workspace.mode = "compare"
        self.workspace.pending = Path(self.model.project_dir) / "Optimization/pending/comparison"
        self.workspace.progress_offset = 0
        atomic_json(self.workspace.pending / "request.json", dict(source_run="Optimization/runs/example",
                    candidate_index=0, study=self.workspace.loaded.to_dict(), candidate=core["candidates"][0]))
        atomic_json(self.workspace.pending / "result.json", {"ok": True, "result": {"backend": "test", "metrics": {"CL": .5}}})
        self.workspace.finished()
        self.assertIs(self.workspace.result, core)
        paths = list((Path(self.model.project_dir) / "Optimization/comparisons").glob("*.json"))
        self.assertEqual(len(paths), 1)
        record = json.loads(paths[0].read_text())
        self.assertEqual(record["candidate"], core["candidates"][0])
        self.assertEqual(record["source_run"], "Optimization/runs/example")

    def test_interrupted_worker_recovers_into_saved_run(self):
        import json
        from uavlib.optimization import evaluate
        from uavlib.optimization.schema import MODEL_VERSION
        from uavlib.optimization.storage import atomic_json
        study = self.workspace.read_editor()
        baseline = evaluate(study)
        self.workspace.run_study = study
        self.workspace.mode = "optimize"
        folder = Path(self.model.project_dir) / "Optimization/pending/interrupted"
        self.workspace.pending = folder
        self.workspace.progress_offset = 0
        atomic_json(folder / "request.json", {"study": study.to_dict(), "mode": "optimize"})
        atomic_json(folder / "execution.json", {"model_version": MODEL_VERSION, "input_hash": study.fingerprint()})
        (folder / "evaluations.jsonl").write_text(json.dumps(baseline.to_dict()) + "\n")
        self.workspace.finished()
        self.assertEqual(self.workspace.result["status"], "interrupted")
        self.assertEqual(len(self.model.data.optimization["runs"]), 1)
        self.assertEqual(self.workspace.candidates.rowCount(), 1)


if __name__ == "__main__":
    unittest.main()
