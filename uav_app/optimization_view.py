"""Desktop study editor and isolated process runner."""
from dataclasses import asdict
from pathlib import Path
import json
import os
import sys
import uuid
from PyQt6.QtCore import QProcess, QTimer, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QLineEdit,
    QMessageBox, QFileDialog, QSpinBox, QCheckBox, QHeaderView,
    QInputDialog, QDialog,
)
from uavlib.optimization import StudyDefinition, template
from uavlib.optimization.schema import OptimizationResult, EvaluationResult
from uavlib.optimization.storage import StudyStore, atomic_json, export_study, project_path
from uavlib.optimization.templates import PARAMETERS, METRICS, FAMILY_PARAMETERS
from uavlib import units
from .views import accent


FAMILIES = (("Fixed wing", "fixed_wing"), ("Multirotor", "multirotor"), ("Helicopter", "helicopter"),
            ("Lift + cruise", "lift_cruise"), ("Rocket", "rocket"))
WORKFLOWS = (("Requirements first", "requirements"), ("Hardware first", "hardware"))
PROPULSIONS = (("Electric", "electric"), ("Fuel", "fuel"))
LAYOUTS = (("Quad X", "quad_x"), ("Quad +", "quad_plus"), ("Quad H", "quad_h"), ("Hex", "hex"),
           ("Y6 coaxial", "y6"), ("Octo", "octo"), ("X8 coaxial", "x8"), ("Tri", "tri"))
SOLVERS = (("Differential evolution — global", "differential_evolution"),
           ("SLSQP — local, continuous only", "slsqp"))
PARAMETER_HELP = {
    "payload": "Mass carried in addition to the airframe, propulsion and energy store.",
    "wing_area": "Reference planform area. If this row says Variable, edit the bounds on tab 4.",
    "aspect_ratio": "Span squared divided by wing area. Values above 16 are outside the conceptual polar.",
    "tail_area": "Horizontal tail area used for the static-margin estimate.",
    "tail_arm": "Distance from the wing quarter-chord to the tail quarter-chord.",
    "cruise_speed": "Speed used by cruise segments. Other segment speeds stay on the mission table.",
    "rotor_diameter": "Diameter of one rotor disk.",
    "rotor_rpm": "Main-rotor or lift-rotor speed.",
    "blade_chord": "Constant blade chord used by the rotor trim model.",
    "blade_count": "Blades per rotor. Use an integer variable when the count itself is a choice.",
    "tail_rotor_diameter": "Tail-rotor diameter. Tail power uses momentum theory.",
    "tail_rotor_arm": "Distance from the main-rotor shaft to the tail rotor.",
    "main_rotor_x": "Main hub, forward of the mass datum. Aircraft datum is the wing leading edge.",
    "main_rotor_height": "Main hub height above the mass datum.",
    "tail_rotor_height": "Tail-rotor height above the mass datum.",
    "arm_length": "Center to motor. Adjacent-rotor clearance uses this length.",
    "arm_diameter": "Outer diameter of the arm tube.",
    "arm_wall": "Wall thickness. Must be less than half the outer diameter.",
    "body_length": "Rocket body length, nose to tail.",
    "body_diameter": "Rocket body outer diameter.",
    "fin_area": "Planform area of one fin set used in the static-margin estimate.",
    "fin_span": "Fin span measured outward from the body.",
    "propellant_mass": "Propellant loaded at ignition. Requirements mode can derive this.",
    "burn_time": "Duration of the constant-thrust burn when no thrust curve is supplied.",
    "recovery_area": "Parachute reference area.",
    "launch_altitude": "Geometric altitude of the launch site.",
}


def fill_choices(combo, pairs):
    combo.clear()
    for label, value in pairs:
        combo.addItem(label, value)


def select_choice(combo, value):
    index = combo.findData(value)
    if index < 0:
        raise ValueError(f"Unknown choice {value}")
    combo.setCurrentIndex(index)


def candidate_rows(candidates):
    rows = []
    for i, row in enumerate(candidates):
        objectives = row.get("objectives", [])
        shown = ", ".join(f"{value:.4g}" for value in objectives) if isinstance(objectives, list) else str(objectives)
        violations = ", ".join(key for key, value in row.get("margins", {}).items() if value < -1e-8)
        rows.append([i, "Yes" if row.get("valid") else "No", "Yes" if row.get("feasible") else "No",
                     shown, violations or "—", "Yes" if row.get("converged") else "No"])
    return rows


def candidate_text(candidate):
    lines = ["Feasible" if candidate.get("feasible") else "Not feasible",
             "Converged" if candidate.get("converged") else "Closure did not converge"]
    if candidate.get("errors"):
        lines.append("Errors: " + "; ".join(candidate["errors"]))
    if candidate.get("warnings"):
        lines.extend(["", "Model warnings", *("  " + item for item in candidate["warnings"])])
    lines.extend(["", "Metrics"])
    for key, value in candidate.get("metrics", {}).items():
        lines.append(f"  {key}: {value:.6g} {METRICS.get(key, '')}".rstrip())
    lines.extend(["", "Design"])
    for key, value in candidate.get("design", {}).items():
        if str(key).startswith("_"):
            continue
        lines.append(f"  {key}: {value:.6g} {PARAMETERS.get(key, ('',))[0]}".rstrip())
    tight = [(key, value) for key, value in candidate.get("margins", {}).items() if value < 0.05]
    if tight:
        lines.extend(["", "Tight or violated margins (normalized, nonnegative is feasible)"])
        for key, value in sorted(tight, key=lambda item: item[1]):
            lines.append(f"  {key}: {value:.4g}")
    record = {key: value for key, value in candidate.items() if key not in ("mission_history", "endurance_history")}
    lines.extend(["", "Record", json.dumps(record, indent=2)])
    return "\n".join(lines)


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return widget


def put_rows(widget, rows):
    widget.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            widget.setItem(i, j, QTableWidgetItem(str(value)))


def rows(widget):
    return [[widget.item(i, j).text().strip() if widget.item(i, j) else ""
             for j in range(widget.columnCount())] for i in range(widget.rowCount())]


class OptimizationWorkspace(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.model = controller.model
        self.project_dir = self.model.project_dir
        self.store = StudyStore(self.project_dir)
        self.study_path = None
        self.result = None
        self.run_study = None
        self.run_path = None
        self.process = None
        self.loaded = template()
        self.layout = QVBoxLayout(self)
        title = QLabel("Aerospace optimization workbench — engineering preview")
        title.setToolTip("A feasible result satisfies the implemented checks. It is not an airworthiness finding.")
        self.layout.addWidget(title)
        self.layout.addWidget(QLabel("Review model assumptions and validity limits before applying a design."))
        toolbar = QHBoxLayout()
        self.saved = QComboBox()
        self.saved.setMinimumWidth(170)
        toolbar.addWidget(self.saved)
        for text, fn in (("Open", self.open_study), ("Save study", self.save_study),
                         ("Duplicate", self.duplicate), ("Import JSON", self.import_study), ("Export", self.export)):
            button = QPushButton(text)
            button.clicked.connect(fn)
            toolbar.addWidget(button)
        self.layout.addLayout(toolbar)
        history_bar = QHBoxLayout()
        self.saved_runs = QComboBox()
        history_bar.addWidget(self.saved_runs, 1)
        open_run = QPushButton("Open saved run")
        open_run.clicked.connect(self.open_run)
        history_bar.addWidget(open_run)
        compare_runs = QPushButton("Compare saved runs")
        compare_runs.clicked.connect(self.compare_runs)
        history_bar.addWidget(compare_runs)
        recover_button = QPushButton("Recover interrupted run")
        recover_button.clicked.connect(self.recover_run)
        history_bar.addWidget(recover_button)
        self.layout.addLayout(history_bar)
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs, 1)

        vehicle_page = QWidget()
        vl = QVBoxLayout(vehicle_page)
        self.name = QLineEdit()
        vl.addWidget(QLabel("Study name"))
        vl.addWidget(self.name)
        row = QHBoxLayout()
        self.family, self.workflow, self.propulsion, self.topology = QComboBox(), QComboBox(), QComboBox(), QComboBox()
        fill_choices(self.family, FAMILIES)
        fill_choices(self.workflow, WORKFLOWS)
        fill_choices(self.propulsion, PROPULSIONS)
        fill_choices(self.topology, LAYOUTS)
        self.family.setToolTip("Vehicle family. Apply it with Load new template.")
        self.workflow.setToolTip("Requirements-first sizes the vehicle. Hardware-first locks parts you enter.")
        self.propulsion.setToolTip("Electric or fuel. Apply it with Load new template.")
        self.topology.setToolTip("Rotor arrangement. Coaxial layouts share disks and pay an interference penalty.")
        for widget in (self.family, self.workflow, self.propulsion, self.topology):
            row.addWidget(widget)
        new = accent(QPushButton("Load new template"))
        new.setToolTip("Replace the open study with a fresh template for the selectors above.")
        new.clicked.connect(self.new_template)
        row.addWidget(new)
        vl.addLayout(row)
        vl.addWidget(QLabel("Changing family, workflow, or propulsion applies only when you load a new template."))
        self.parameters = table(["Parameter ID", "Value (unit suffix accepted)", "SI unit", "Role"])
        vl.addWidget(self.parameters)
        vl.addWidget(QLabel("Templates are conceptual assumptions. Hardware mode requires your installed parts and performance data."))
        self.tabs.addTab(vehicle_page, "1 · Vehicle")

        mission_page = QWidget()
        ml = QVBoxLayout(mission_page)
        ml.addWidget(QLabel("Mission kinds: cruise, hover, climb, descent, transition, manual. Duration in seconds."))
        self.mission = table(["Name", "Kind", "Duration s", "Speed m/s", "Altitude m", "Climb m/s", "End speed m/s", "End altitude m", "Manual power W"])
        ml.addWidget(self.mission)
        self._row_buttons(ml, self.mission)
        self.reserve = QLineEdit("0.2")
        ml.addWidget(QLabel("Reserve fraction (0–1)"))
        ml.addWidget(self.reserve)
        ml.addWidget(QLabel("Requirements: metric IDs are listed on the Results page; sense is >=, <= or ==. Blank segment applies to overall metric."))
        self.requirements = table(["Metric", "Limit", "Sense", "Scale", "Tolerance", "Segment"])
        ml.addWidget(self.requirements)
        self._row_buttons(ml, self.requirements)
        self.tabs.addTab(mission_page, "2 · Requirements / mission")

        hardware_page = QWidget()
        hl = QVBoxLayout(hardware_page)
        hl.addWidget(QLabel("Fixed installed components. Mass is per item; position is from the model datum. Properties are SI JSON maps."))
        self.hardware = table(["ID", "Kind", "Mass kg", "Quantity", "Position m", "Properties JSON", "Source", "Conceptual true/false"])
        hl.addWidget(self.hardware)
        self._row_buttons(hl, self.hardware)
        import_curve = QPushButton("Import SI performance curve for selected component…")
        import_curve.clicked.connect(self.import_curve)
        hl.addWidget(import_curve)
        hl.addWidget(QLabel("Technology assumptions (editable; not manufacturer data)"))
        self.assumptions = table(["Assumption", "Value"])
        hl.addWidget(self.assumptions)
        self.tabs.addTab(hardware_page, "3 · Hardware / assumptions")

        variables_page = QWidget()
        dl = QVBoxLayout(variables_page)
        dl.addWidget(QLabel("Only explicitly free variables may change. Hardware-owned dimensions and capacities are locked."))
        self.variables = table(["ID", "Initial", "Lower", "Upper", "Unit", "Scale", "Free true/false", "Integer true/false"])
        dl.addWidget(self.variables)
        self._row_buttons(dl, self.variables)
        self.objectives = table(["Metric", "min / max", "Scale"])
        dl.addWidget(self.objectives)
        self._row_buttons(dl, self.objectives)
        self.scenarios = table(["Scenario", "Altitude offset m", "Speed factor", "Payload delta kg"])
        dl.addWidget(self.scenarios)
        self._row_buttons(dl, self.scenarios)
        self.robust = QCheckBox("Require every scenario to be feasible; optimize worst-case objective")
        dl.addWidget(self.robust)
        self.tabs.addTab(variables_page, "4 · Variables / objectives")

        run_page = QWidget()
        rl = QVBoxLayout(run_page)
        run_row = QHBoxLayout()
        self.solver = QComboBox()
        fill_choices(self.solver, SOLVERS)
        self.solver.setToolTip("SLSQP is for continuous variables. Differential evolution accepts integers.")
        run_row.addWidget(self.solver)
        self.refine = QCheckBox("Local refinement")
        self.refine.setToolTip("After the global search, hold integer choices fixed and polish continuous variables with SLSQP. Uses part of the evaluation budget. Single objective only.")
        run_row.addWidget(self.refine)
        self.budget = QSpinBox()
        self.budget.setRange(1, 100000)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2147483647)
        for label, widget in (("Evaluation budget", self.budget), ("Seed", self.seed)):
            run_row.addWidget(QLabel(label))
            run_row.addWidget(widget)
        rl.addLayout(run_row)
        self.run_buttons = []
        buttons = QHBoxLayout()
        for text, mode in (("Evaluate baseline", "evaluate"), ("Optimize", "optimize"),
                           ("Sweep", "sweep"), ("Sensitivity", "sensitivity"), ("Uncertainty", "uncertainty")):
            button = accent(QPushButton(text)) if mode == "optimize" else QPushButton(text)
            button.setToolTip({
                "evaluate": "Analyse the current design once, with no search.",
                "optimize": "Search the free variables. Run a baseline first if you want that point on its own.",
                "sweep": "Evaluate the grid or Latin-hypercube specification below.",
                "sensitivity": "Finite-difference the metrics against each continuous free variable.",
                "uncertainty": "Sample technology assumptions with the installed vehicle held fixed.",
            }[mode])
            button.clicked.connect(lambda _, m=mode: self.start(m))
            self.run_buttons.append(button)
            buttons.addWidget(button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        buttons.addWidget(self.cancel_button)
        rl.addLayout(buttons)
        rl.addWidget(QLabel('Sweep/uncertainty specification (JSON). Example uncertainty: {"samples":100,"inputs":{"cd0":{"lower":0.03,"upper":0.04}}}'))
        self.specification = QTextEdit('{"kind":"latin_hypercube","samples":25}')
        self.specification.setMaximumHeight(110)
        rl.addWidget(self.specification)
        self.progress = QLabel("Ready. Baseline evaluation runs before optimization.")
        self.progress.setWordWrap(True)
        rl.addWidget(self.progress)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        rl.addWidget(self.log)
        self.tabs.addTab(run_page, "5 · Run")

        result_page = QWidget()
        rr = QVBoxLayout(result_page)
        self.candidates = table(["Candidate", "Valid", "Feasible", "Objectives", "Violations", "Converged"])
        self.candidates.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.candidates.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.candidates.itemSelectionChanged.connect(self.select_result)
        rr.addWidget(self.candidates)
        controls = QHBoxLayout()
        comparison = QPushButton("External comparison…")
        comparison.clicked.connect(self.external_comparison)
        controls.addWidget(comparison)
        self.chart_kind = QComboBox()
        self.chart_kind.addItems(["Mission power", "Mission energy", "Endurance mission", "Mass breakdown", "Constraint margins", "Convergence", "Pareto", "Uncertainty"])
        self.chart_kind.currentTextChanged.connect(self.select_result)
        controls.addWidget(self.chart_kind)
        self.pareto_x, self.pareto_y = QComboBox(), QComboBox()
        for combo in (self.pareto_x, self.pareto_y):
            combo.addItems(["Objective 1", "Objective 2", "Objective 3"])
            combo.currentIndexChanged.connect(self.select_result)
            controls.addWidget(combo)
        self.pareto_y.setCurrentIndex(1)
        save_plot = QPushButton("Save plot")
        save_plot.clicked.connect(self.save_plot)
        controls.addWidget(save_plot)
        self.stage = QComboBox()
        self.stage.addItems(["Conceptual", "Preliminary", "Detail"])
        controls.addWidget(self.stage)
        apply = QPushButton("Apply selected design…")
        apply.clicked.connect(self.apply_selected)
        controls.addWidget(apply)
        rr.addLayout(controls)
        self.chart = QLabel("Run a study, then select a candidate to plot it.")
        self.chart.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart.setMinimumHeight(170)
        rr.addWidget(self.chart)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        rr.addWidget(self.details)
        self.tabs.addTab(result_page, "6 · Compare results")
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.poll)
        self.refresh_saved()
        self.load_editor(self.loaded)

    def _row_buttons(self, layout, widget):
        row = QHBoxLayout()
        add, remove = QPushButton("Add row"), QPushButton("Remove selected row")
        add.clicked.connect(lambda: widget.insertRow(widget.rowCount()))
        remove.clicked.connect(lambda: widget.removeRow(widget.currentRow()) if widget.currentRow() >= 0 else None)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        layout.addLayout(row)

    def refresh_saved(self):
        self.saved.clear()
        for item in self.model.data.optimization["studies"]:
            self.saved.addItem(item["name"], item["path"])
        self.saved_runs.clear()
        for item in self.model.data.optimization["runs"]:
            self.saved_runs.addItem(item["study"] + " · " + item["status"], item["path"])

    def open_run(self):
        relative = self.saved_runs.currentData()
        if not relative:
            return
        try:
            folder = project_path(self.project_dir, relative)
            self.run_study = StudyDefinition.from_dict(json.loads((folder / "study.json").read_text(encoding="utf-8")))
            self.result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
            self.run_path = relative
            self.study_path = None
            self.load_editor(self.run_study)
            put_rows(self.candidates, candidate_rows(self.result.get("candidates", [])))
            if self.candidates.rowCount():
                self.candidates.selectRow(0)
            self.tabs.setCurrentIndex(5)
        except Exception as exc:
            self.error(exc)

    def compare_runs(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Compare saved designs — check assumptions and model validity")
        layout = QVBoxLayout(dialog)
        comparison = table(["Study", "Candidate", "Status", "Mass kg", "Endurance s", "Range m", "Apogee m", "Power W"])
        data = []
        try:
            for item in self.model.data.optimization["runs"]:
                result = json.loads((project_path(self.project_dir, item["path"]) / "result.json").read_text(encoding="utf-8"))
                for i, candidate in enumerate(result.get("candidates", [])):
                    if not candidate["valid"]:
                        continue
                    metrics = candidate["metrics"]
                    data.append([item["study"], i, "Feasible" if candidate["feasible"] else "Infeasible"] +
                                [f"{metrics[k]:.5g}" if k in metrics else "—" for k in
                                 ("takeoff_mass", "endurance", "range", "apogee", "installed_power")])
            put_rows(comparison, data)
            comparison.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            layout.addWidget(comparison)
            dialog.resize(1100, 500)
            dialog.exec()
        except Exception as exc:
            self.error(exc)

    def import_curve(self):
        index = self.hardware.currentRow()
        if index < 0:
            self.error("Select the installed component that owns the curve first.")
            return
        key, ok = QInputDialog.getItem(self, "Performance curve", "SI curve property", [
            "efficiency_map", "max_power_map", "performance_map", "ocv_map", "resistance_map", "fuel_flow_map", "thrust_curve", "propellant_curve", "cd_mach", "cp_mach"], 0, False)
        if not ok:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import SI x,y curve", "", "CSV (*.csv)")
        if not path:
            return
        try:
            from uavlib.optimization.data import read_curve_csv, read_propeller_csv
            points = read_propeller_csv(path) if key == "performance_map" else read_curve_csv(path)
            item = self.hardware.item(index, 5)
            properties = json.loads(item.text() if item and item.text().strip() else "{}")
            relative, digest = self.store.import_data(path)
            self.loaded.source_hashes[relative] = digest
            properties[key] = points
            self.hardware.setItem(index, 5, QTableWidgetItem(json.dumps(properties)))
            self.hardware.setItem(index, 6, QTableWidgetItem(relative))
        except Exception as exc:
            self.error(exc)

    def new_template(self):
        try:
            self.loaded = template(self.family.currentData(), self.workflow.currentData(), self.propulsion.currentData())
            self.study_path = None
            self.load_editor(self.loaded)
        except Exception as exc:
            self.error(exc)

    def load_editor(self, study):
        self.loaded = study
        self.name.setText(study.name)
        select_choice(self.family, study.vehicle.family)
        select_choice(self.workflow, study.workflow)
        select_choice(self.propulsion, study.vehicle.propulsion)
        select_choice(self.topology, study.vehicle.layout)
        variable_keys = {v.key for v in study.variables}
        defaults = template(study.vehicle.family, study.workflow, study.vehicle.propulsion).vehicle.parameters
        put_rows(self.parameters, [[k, study.vehicle.parameters.get(k, defaults[k]), PARAMETERS.get(k, ("",))[0],
                                   "Variable: edit in tab 4" if k in variable_keys else "Fixed"]
                                  for k in FAMILY_PARAMETERS[study.vehicle.family]])
        for i, row in enumerate(rows(self.parameters)):
            for col in (0, 2, 3):
                self.parameters.item(i, col).setFlags(self.parameters.item(i, col).flags() & ~Qt.ItemFlag.ItemIsEditable)
            note = PARAMETER_HELP.get(row[0], "")
            if row[0] in variable_keys:
                self.parameters.item(i, 1).setFlags(self.parameters.item(i, 1).flags() & ~Qt.ItemFlag.ItemIsEditable)
                note = (note + " " if note else "") + "This value is a free variable: edit its initial value and bounds on tab 4."
            if note:
                for col in range(self.parameters.columnCount()):
                    item = self.parameters.item(i, col)
                    if item:
                        item.setToolTip(note)
        put_rows(self.assumptions, list(study.vehicle.assumptions.items()))
        put_rows(self.mission, [[s.name, s.kind, s.duration, s.speed, s.altitude, s.climb_rate,
                                "" if s.end_speed is None else s.end_speed,
                                "" if s.end_altitude is None else s.end_altitude,
                                "" if s.power is None else s.power] for s in study.mission.segments])
        put_rows(self.hardware, [[c.id, c.kind, c.mass, c.quantity, c.position, json.dumps(c.properties), c.source, str(c.conceptual).lower()]
                                for c in study.vehicle.components])
        put_rows(self.variables, [[v.key, v.initial, v.lower, v.upper, v.unit, v.scale, str(v.free).lower(), str(v.integer).lower()]
                                 for v in study.variables])
        put_rows(self.requirements, [[r.metric, r.limit, r.sense, r.scale, r.tolerance, r.segment] for r in study.requirements])
        put_rows(self.objectives, [[o.metric, o.sense, o.scale] for o in study.objectives])
        put_rows(self.scenarios, [[s.name, s.altitude_offset, s.speed_factor, s.payload_delta] for s in study.scenarios])
        self.reserve.setText(str(study.mission.reserve_fraction))
        self.robust.setChecked(study.robust)
        self.seed.setValue(study.seed)
        self.budget.setValue(study.max_evaluations)
        select_choice(self.solver, study.solver)
        self.refine.setChecked(bool(study.local_refinement))
        self.details.setPlainText(
            "Run a study, then select a candidate.\n\n"
            "Metrics you can use as objectives or requirements:\n"
            + "\n".join(f"  {key}  ({unit or 'dimensionless'})" for key, unit in METRICS.items()))

    def read_editor(self):
        chosen = (self.family.currentData(), self.workflow.currentData(), self.propulsion.currentData())
        loaded = (self.loaded.vehicle.family, self.loaded.workflow, self.loaded.vehicle.propulsion)
        if chosen != loaded:
            raise ValueError("The family, workflow, or propulsion selector does not match this study. "
                             "Click Load new template to build that problem, or set the selector back before saving.")
        data = self.loaded.to_dict()
        data.update(name=self.name.text(), workflow=self.workflow.currentData(), seed=self.seed.value(),
                    max_evaluations=self.budget.value(), solver=self.solver.currentData(),
                    robust=self.robust.isChecked(), local_refinement=self.refine.isChecked())
        data["vehicle"].update(family=self.family.currentData(), propulsion=self.propulsion.currentData(),
                               layout=self.topology.currentData())
        data["vehicle"]["parameters"].update({k: self.number(v, unit)
                                           for k, v, unit, role in rows(self.parameters)})
        data["vehicle"]["assumptions"] = {k: float(v) for k, v in rows(self.assumptions)}
        data["vehicle"]["components"] = [dict(id=i, kind=k, mass=self.number(m, "kg"), quantity=int(n), position=self.number(x, "m"),
                                              properties=json.loads(p or "{}"), source=source, conceptual=self.boolean(conceptual or "false"))
                                         for i, k, m, n, x, p, source, conceptual in rows(self.hardware)]
        data["mission"] = dict(reserve_fraction=self.number(self.reserve.text(), ""), segments=[
            dict(name=n, kind=k, duration=self.number(t, "s"), speed=self.number(v, "m/s"), altitude=self.number(h, "m"), climb_rate=self.number(c, "m/s"),
                 end_speed=self.number(ev, "m/s") if ev else None, end_altitude=self.number(eh, "m") if eh else None, power=self.number(power, "W") if power else None)
            for n, k, t, v, h, c, ev, eh, power in rows(self.mission)])
        data["variables"] = [dict(key=k, initial=self.number(i, u), lower=self.number(lo, u), upper=self.number(hi, u), unit=u,
                                   scale=self.number(s, u), free=self.boolean(f), integer=self.boolean(n))
                              for k, i, lo, hi, u, s, f, n in rows(self.variables)]
        data["requirements"] = [dict(metric=m, limit=self.number(l, METRICS.get(m, "")), sense=s,
                                     scale=self.number(sc, METRICS.get(m, "")), tolerance=self.number(t, METRICS.get(m, "")), segment=seg)
                                 for m, l, s, sc, t, seg in rows(self.requirements)]
        data["objectives"] = [dict(metric=m, sense=s, scale=float(sc)) for m, s, sc in rows(self.objectives)]
        data["scenarios"] = [dict(name=n, altitude_offset=self.number(h, "m"), speed_factor=self.number(v, ""), payload_delta=self.number(p, "kg"))
                              for n, h, v, p in rows(self.scenarios)]
        study = StudyDefinition.from_dict(data)
        study.validate()
        return study

    @staticmethod
    def number(value, unit):
        if unit == "rpm":
            return float(value.lower().removesuffix("rpm").strip())
        result = units.parse(value, unit, None)
        if result is None:
            raise ValueError("A numeric value is required")
        return result

    @staticmethod
    def boolean(value):
        if value.lower() not in ("true", "false"):
            raise ValueError("Boolean cells must be true or false")
        return value.lower() == "true"

    def error(self, exc):
        QMessageBox.warning(self, "Optimization", str(exc))

    def save_study(self):
        try:
            study = self.read_editor()
            self.study_path = self.store.save_study(study, self.study_path)
            entries = self.model.data.optimization["studies"]
            entries[:] = [e for e in entries if e["path"] != self.study_path]
            entries.append({"name": study.name, "path": self.study_path})
            self.controller.save_project()
            self.refresh_saved()
            return study
        except Exception as exc:
            self.error(exc)
            return None

    def open_study(self):
        if self.saved.currentData():
            try:
                self.study_path = self.saved.currentData()
                self.load_editor(self.store.load_study(self.study_path))
            except Exception as exc:
                self.error(exc)

    def duplicate(self):
        self.study_path = None
        self.name.setText(self.name.text() + " copy")
        self.save_study()

    def import_study(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import study", "", "JSON (*.json)")
        if path:
            try:
                self.load_editor(StudyDefinition.from_dict(json.loads(Path(path).read_text(encoding="utf-8"))))
                self.study_path = None
            except Exception as exc:
                self.error(exc)

    def export(self):
        directory = QFileDialog.getExistingDirectory(self, "Export study and Python runner")
        if directory:
            try:
                study = self.read_editor()
                if self.result and self.run_study and study.fingerprint() != self.run_study.fingerprint():
                    raise ValueError("Results are stale. Re-run before exporting them with this study.")
                export_study(study, directory, self.result)
            except Exception as exc:
                self.error(exc)

    def start(self, mode):
        if self.process:
            return
        study = self.save_study()
        if study is None:
            return
        try:
            specification = json.loads(self.specification.toPlainText() or "{}")
            self.run_study = study
            self.mode = mode
            self.pending = Path(self.project_dir) / "Optimization" / "pending" / uuid.uuid4().hex
            self.pending.mkdir(parents=True)
            atomic_json(self.pending / "request.json", {"study": study.to_dict(), "mode": mode, "specification": specification})
            self.progress_offset = 0
            self.process = QProcess(self)
            self.process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
            self.process.finished.connect(self.finished)
            self.process.errorOccurred.connect(self.process_error)
            if getattr(sys, "frozen", False):
                args = ["--optimization-worker", str(self.pending)]
            else:
                args = ["-B", "-m", "uavlib.optimization.worker", str(self.pending)]
            self.process.start(sys.executable, args)
            for button in self.run_buttons:
                button.setEnabled(False)
            self.cancel_button.setEnabled(True)
            self.timer.start()
            self.log.clear()
            self.progress.setText("Running baseline / study in an isolated process…")
        except Exception as exc:
            self.error(exc)

    def recover_run(self):
        if self.process:
            self.error("Wait for the active worker to stop before recovering a run.")
            return
        path = QFileDialog.getExistingDirectory(self, "Select interrupted run folder", str(Path(self.project_dir) / "Optimization" / "pending"))
        if not path:
            return
        try:
            folder = Path(path).resolve()
            pending_root = (Path(self.project_dir) / "Optimization" / "pending").resolve()
            if not folder.is_relative_to(pending_root):
                raise ValueError("Select a pending run from this project")
            request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
            if request.get("mode") == "compare":
                raise ValueError("External comparisons must be rerun after interruption")
            self.pending = folder
            self.mode = request.get("mode", "optimize")
            self.run_study = StudyDefinition.from_dict(request["study"])
            self.load_editor(self.run_study)
            self.study_path = None
            self.progress_offset = 0
            self.finished()
        except Exception as exc:
            self.error(exc)

    def external_comparison(self):
        if self.process:
            return
        index = self.candidates.currentRow()
        if not self.result or index < 0 or not self.run_study:
            self.error("Select a valid candidate from a saved run first.")
            return
        candidate = self.result["candidates"][index]
        if not candidate["valid"]:
            self.error("External comparison requires a valid candidate.")
            return
        backend, ok = QInputDialog.getItem(self, "External comparison", "Backend", ["aerosandbox", "openvsp", "rocketpy"], 0, False)
        if not ok:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Comparison configuration JSON", "", "JSON (*.json)")
        if not path:
            return
        python, _ = QFileDialog.getOpenFileName(self, "Python executable with the optional backend and matching uavlib installed", "", "Python (python.exe);;All files (*)")
        if not python:
            return
        try:
            config = json.loads(Path(path).read_text(encoding="utf-8"))
            self.mode = "compare"
            self.pending = Path(self.project_dir) / "Optimization" / "pending" / uuid.uuid4().hex
            self.pending.mkdir(parents=True)
            atomic_json(self.pending / "request.json", dict(study=self.run_study.to_dict(), mode="compare",
                        backend=backend, candidate=candidate, config=config, source_run=self.run_path, candidate_index=index))
            self.progress_offset = 0
            self.process = QProcess(self)
            self.process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
            self.process.finished.connect(self.finished)
            self.process.errorOccurred.connect(self.process_error)
            self.process.start(python, ["-B", "-m", "uavlib.optimization.worker", str(self.pending)])
            for button in self.run_buttons:
                button.setEnabled(False)
            self.cancel_button.setEnabled(True)
            self.timer.start()
            self.log.clear()
            self.progress.setText("Running external comparison in its separate Python environment…")
        except Exception as exc:
            self.error(exc)

    def process_error(self, error):
        if self.process and error == QProcess.ProcessError.FailedToStart:
            self.log.append(self.process.errorString())
            self.finished(-1)

    def poll(self):
        path = self.pending / "progress.jsonl"
        if path.exists():
            with path.open("r", encoding="utf-8") as stream:
                stream.seek(self.progress_offset)
                while True:
                    before = stream.tell()
                    line = stream.readline()
                    if not line or not line.endswith("\n"):
                        self.progress_offset = before
                        break
                    row = json.loads(line)
                    self.progress.setText(f"Evaluation {row['evaluation']} · valid {row['valid']} · feasible {row['feasible']} · objectives {row['objectives']} · best feasible {row.get('best_feasible_objectives')}")
                    if row["errors"]:
                        self.log.append("; ".join(row["errors"]))
                    self.progress_offset = stream.tell()

    def cancel(self):
        if self.process:
            (self.pending / "cancel").touch()
            process = self.process
            QTimer.singleShot(3000, lambda: process.kill() if process.state() != QProcess.ProcessState.NotRunning else None)
            self.progress.setText("Cancellation requested; completed evaluations remain on disk.")

    def shutdown(self):
        self.timer.stop()
        if self.process:
            (self.pending / "cancel").touch()
            if not self.process.waitForFinished(1000):
                self.process.kill()
                self.process.waitForFinished(1000)

    def finished(self, exit_code=0, *_):
        self.timer.stop()
        self.poll()
        process, self.process = self.process, None
        if process:
            stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
            if stderr:
                self.log.append(stderr)
            process.deleteLater()
        self.cancel_button.setEnabled(False)
        for button in self.run_buttons:
            button.setEnabled(True)
        path = self.pending / "result.json"
        if not path.exists():
            from uavlib.optimization.worker import recover
            try:
                recovered = recover(self.pending)
                if not recovered["ok"]:
                    self.progress.setText(recovered["error"])
                    return
            except Exception as exc:
                self.progress.setText("Recovery failed: " + str(exc))
                return
        try:
            response = json.loads(path.read_text(encoding="utf-8"))
            if not response["ok"]:
                raise ValueError(response["error"])
            data = response["result"]
            if self.mode == "compare":
                request = json.loads((self.pending / "request.json").read_text(encoding="utf-8"))
                relative = f"Optimization/comparisons/{uuid.uuid4().hex}.json"
                record = dict(result=data, source_run=request["source_run"], candidate_index=request["candidate_index"],
                              study=request["study"], candidate=request["candidate"])
                atomic_json(project_path(self.project_dir, relative), record)
                self.details.setPlainText(json.dumps(record, indent=2))
                self.progress.setText("External comparison saved: " + relative)
                self.tabs.setCurrentIndex(5)
                return
            if self.mode == "evaluate":
                data = OptimizationResult("evaluated", EvaluationResult(**data),
                                          [EvaluationResult(**data)], input_hash=self.run_study.fingerprint()).to_dict()
            elif self.mode != "optimize":
                data = {**data, "candidates": data["evaluations"], "status": data.get("status", data["kind"])}
            self.result = data
            # Persist exact snapshots before updating the project index.
            self.run_path = f"Optimization/runs/{uuid.uuid4().hex}"
            folder = project_path(self.project_dir, self.run_path)
            atomic_json(folder / "study.json", self.run_study.to_dict())
            atomic_json(folder / "result.json", data)
            if self.model.project_dir == self.project_dir:
                self.model.data.optimization["runs"].append({"study": self.run_study.name, "path": self.run_path,
                                                             "status": data["status"], "input_hash": self.run_study.fingerprint()})
                self.controller.save_project()
                self.refresh_saved()
            self.progress.setText(data["status"] + " · " + data.get("solver_message", ""))
            candidates = data.get("candidates", [])
            put_rows(self.candidates, candidate_rows(candidates))
            if candidates:
                self.candidates.selectRow(0)
            else:
                self.details.setPlainText(json.dumps(data.get("baseline", data), indent=2))
            self.tabs.setCurrentIndex(5)
        except Exception as exc:
            self.progress.setText("Failed: " + str(exc))
            self.log.append(str(exc))

    def select_result(self, *_):
        index = self.candidates.currentRow()
        if not self.result or index < 0:
            return
        candidate = self.result["candidates"][index]
        text = candidate_text(candidate)
        if "summary" in self.result:
            text += "\n\nStudy summary\n" + json.dumps(self.result["summary"], indent=2)
        self.details.setPlainText(text)
        try:
            from uavlib.optimization.charts import chart_png
            png = chart_png(self.result, candidate, self.chart_kind.currentText(),
                            (self.pareto_x.currentIndex(), self.pareto_y.currentIndex()))
            image = QPixmap()
            image.loadFromData(png)
            self.chart.setPixmap(image.scaledToWidth(min(780, max(300, self.width() - 60))))
        except Exception as exc:
            self.chart.setText(str(exc))

    def save_plot(self):
        index = self.candidates.currentRow()
        if not self.result or index < 0 or not self.run_path:
            return
        try:
            from uavlib.optimization.charts import chart_png
            data = chart_png(self.result, self.result["candidates"][index], self.chart_kind.currentText(),
                             (self.pareto_x.currentIndex(), self.pareto_y.currentIndex()))
            relative = f"{self.run_path}/charts/{uuid.uuid4().hex}.png"
            path = project_path(self.project_dir, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.progress.setText("Plot saved: " + relative)
        except Exception as exc:
            self.error(exc)

    def apply_selected(self):
        index = self.candidates.currentRow()
        if not self.result or index < 0:
            return
        try:
            if self.model.project_dir != self.project_dir:
                raise ValueError("The active project changed")
            study = self.read_editor()
            if self.store.stale(study, self.result):
                raise ValueError("Result is stale; rerun this study before applying")
            result = self.result["candidates"][index]
            if not result["valid"] or not result["feasible"]:
                raise ValueError("Only physically feasible, valid candidates can be applied")
            name = self.stage.currentText()
            stage = self.model.data.stages[name]
            values = {f"Optimization: {key}": f"{value:.8g} {METRICS.get(key, '')}".strip()
                      for key, value in result["metrics"].items()}
            values.update({f"Design: {key}": f"{value:.8g} {PARAMETERS.get(key, ('',))[0]}".strip()
                           for key, value in result["design"].items() if not key.startswith("_")})
            if "takeoff_mass" in result["metrics"]:
                values["Max Takeoff Weight (W_TO)"] = f"{result['metrics']['takeoff_mass'] * 9.80665:.8g} N"
            if study.vehicle.family in ("fixed_wing", "lift_cruise"):
                values["Wing Area (S)"] = f"{result['design']['wing_area']:.8g} m^2"
            if "installed_power" in result["metrics"]:
                values["Engine Thrust/Power (T/P)"] = f"{result['metrics']['installed_power']:.8g} W"
            preview = "\n".join(f"{k}: {stage.parameters.get(k, '(new)')} → {v}" for k, v in values.items())
            if QMessageBox.question(self, "Apply design and reset stage review?", preview) != QMessageBox.StandardButton.Yes:
                return
            self.controller._sync_ui_to_model()
            stage.parameters.update(values)
            existing = {p["name"] for p in stage.parameters_config}
            stage.parameters_config.extend({"name": k, "required": False} for k in values if k not in existing)
            stage.completed = stage.review_state = False
            sv = self.controller.view.stage_views[name]
            sv["review_cb"].setChecked(False)
            self.controller._refresh_params(name)
            self.controller._update_stage_status()
            self.model.data.optimization["applied"].append(dict(stage=name, run=self.run_path, candidate=index,
                                                               study=study.name, input_hash=study.fingerprint()))
            self.controller.save_project()
        except Exception as exc:
            self.error(exc)
