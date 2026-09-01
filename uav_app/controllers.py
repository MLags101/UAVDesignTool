import json
import os
import shutil
import webbrowser

from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox,
                             QFileDialog, QFrame, QGroupBox, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                             QPushButton, QTextEdit, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

from .generator import generate_overleaf_zip
from .models import IMAGES_DIRNAME, STAGE_NAMES, ProjectModel, sanitize_filename
from .theme import APP_NAME, ORG_NAME, THEMES, apply_theme, load_theme_name, monospace_font
from .tool_base import ToolError, ToolManager, ToolWorker
from .views import IMAGE_FILTER, MainWindow, accent, set_role

MAX_RECENT_PROJECTS = 8
AUTOSAVE_DELAY_MS = 1500


def fuzzy_match(needle: str, haystack: str) -> bool:
    """True when every character of `needle` appears in order in `haystack`."""
    needle, haystack = needle.lower(), haystack.lower()
    if not needle:
        return True
    pos = 0
    for char in needle:
        pos = haystack.find(char, pos)
        if pos < 0:
            return False
        pos += 1
    return True


class CommandPalette(QDialog):
    """Ctrl+Shift+P launcher with fuzzy filtering and keyboard navigation."""

    def __init__(self, parent=None, commands=None):
        super().__init__(parent)
        self.setWindowTitle("Command Palette")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Popup)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Type a command…")
        layout.addWidget(self.search_edit)

        self.cmd_list = QListWidget()
        self.cmd_list.setMinimumHeight(280)
        layout.addWidget(self.cmd_list)

        self.commands = commands or {}
        self._filter_list("")

        self.search_edit.textChanged.connect(self._filter_list)
        self.cmd_list.itemActivated.connect(self._execute_item)
        self.search_edit.setFocus()

    def _filter_list(self, text):
        self.cmd_list.clear()
        for name in self.commands:
            if fuzzy_match(text, name):
                self.cmd_list.addItem(name)
        if self.cmd_list.count():
            self.cmd_list.setCurrentRow(0)

    def _execute_item(self, item):
        func = self.commands.get(item.text())
        self.accept()
        if func:
            func()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.cmd_list.currentItem():
                self._execute_item(self.cmd_list.currentItem())
        elif key == Qt.Key.Key_Escape:
            self.reject()
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            # Arrow keys drive the list even though the search box has focus.
            count = self.cmd_list.count()
            if count:
                step = 1 if key == Qt.Key.Key_Down else -1
                self.cmd_list.setCurrentRow((self.cmd_list.currentRow() + step) % count)
        else:
            super().keyPressEvent(event)


class ProjectController:
    def __init__(self, view: MainWindow, model: ProjectModel):
        self.view = view
        self.model = model
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.theme_name = load_theme_name()

        self.autosave_timer = QTimer()
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self._auto_save)

        self.detached_stages = {}
        self.tool_workers = []
        self.current_tool_inputs = {}
        self.tool_output = None
        self._dirty = False
        self._loading = False

        self._bind_start_page()

    # ------------------------------------------------------------ start page
    def _bind_start_page(self):
        self.view.new_btn.clicked.connect(self.new_project)
        self.view.load_btn.clicked.connect(self.load_project)
        self.view.recent_list.itemActivated.connect(self._open_recent)
        self.view.close_requested.connect(self._on_close)
        self.view.show_recent_projects(self._recent_projects())

    def _recent_projects(self):
        stored = self.settings.value("recent_projects", []) or []
        if isinstance(stored, str):
            stored = [stored]
        return [(os.path.splitext(os.path.basename(p))[0], p)
                for p in stored if os.path.exists(p)]

    def _remember_project(self, json_path):
        if not json_path:
            return
        json_path = os.path.abspath(json_path)
        stored = self.settings.value("recent_projects", []) or []
        if isinstance(stored, str):
            stored = [stored]
        stored = [p for p in stored if os.path.abspath(p) != json_path]
        stored.insert(0, json_path)
        self.settings.setValue("recent_projects", stored[:MAX_RECENT_PROJECTS])

    def _open_recent(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            self._load_from_path(path)
        else:
            QMessageBox.warning(self.view, "Missing Project",
                                "That project file no longer exists.")
            self.view.show_recent_projects(self._recent_projects())

    # ------------------------------------------------------------- lifecycle
    def new_project(self):
        dialog = QDialog(self.view)
        dialog.setWindowTitle("New Project")
        dialog.setModal(True)
        dialog.setMinimumWidth(460)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Project Name:"))
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("e.g. Albatross Mk II")
        layout.addWidget(name_edit)

        layout.addWidget(QLabel("Author:"))
        author_edit = QLineEdit()
        layout.addWidget(author_edit)

        layout.addWidget(QLabel("Summary:"))
        summary_edit = QTextEdit()
        summary_edit.setMaximumHeight(110)
        layout.addWidget(summary_edit)

        layout.addWidget(QLabel("Optional Image:"))
        img_layout = QHBoxLayout()
        img_path_edit = QLineEdit()
        img_browse_btn = QPushButton("Browse…")
        img_browse_btn.clicked.connect(lambda: self._browse_image(img_path_edit))
        img_layout.addWidget(img_path_edit)
        img_layout.addWidget(img_browse_btn)
        layout.addLayout(img_layout)

        hint = set_role(QLabel("You will be asked where to create the project folder."), "subtle")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        create_btn = accent(QPushButton("Create Project"))
        buttons.addButton(create_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def on_create():
            name = name_edit.text().strip()
            if not name:
                QMessageBox.warning(dialog, "Incomplete", "Project name is required.")
                return
            parent_folder = QFileDialog.getExistingDirectory(dialog, "Select Project Folder")
            if not parent_folder:
                return
            try:
                self.model.create_project(name, author_edit.text().strip(),
                                          summary_edit.toPlainText(),
                                          img_path_edit.text().strip(), parent_folder)
            except OSError as exc:
                QMessageBox.critical(dialog, "Error", f"Could not create project: {exc}")
                return
            dialog.accept()
            self._remember_project(self.model.json_path)
            self._setup_project_ui(is_loaded=False)

        create_btn.clicked.connect(on_create)
        dialog.exec()

    def _browse_image(self, line_edit):
        file, _ = QFileDialog.getOpenFileName(self.view, "Select Image", "", IMAGE_FILTER)
        if file:
            line_edit.setText(file)

    def load_project(self):
        json_file, _ = QFileDialog.getOpenFileName(
            self.view, "Open Project", "", "UAV Project (*.json)")
        if json_file:
            self._load_from_path(json_file)

    def _load_from_path(self, json_file):
        try:
            self.model.load_project(json_file)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            QMessageBox.critical(self.view, "Error", f"Failed to load project:\n{exc}")
            return
        self._remember_project(self.model.json_path)
        self._setup_project_ui(is_loaded=True)

    def _setup_project_ui(self, is_loaded=False):
        self._loading = True
        # Keep each project's bundled copy of uavlib current with the app's.
        try:
            ToolManager.sync_library(self.model.project_dir)
        except OSError:
            pass
        self.view.init_project_ui()
        self._apply_theme(self.theme_name, announce=False)
        self.view.setWindowTitle(f"UAV Design Organizer — {self.model.data.name}")
        self.view.project_name_label.setText(self.model.data.name)
        self.view.project_author_label.setText(self.model.data.author)

        v = self.view
        v.save_action.triggered.connect(self.save_project)
        v.export_action.triggered.connect(self.export_params)
        v.import_action.triggered.connect(self.import_params)
        v.import_tool_action.triggered.connect(self.import_tool)
        v.generate_action.triggered.connect(self.generate_report)
        v.quit_action.triggered.connect(self.view.close)
        v.command_palette_action.triggered.connect(self.show_command_palette)
        v.theme_action.triggered.connect(self.toggle_theme)
        v.shortcuts_action.triggered.connect(self.show_shortcuts)
        v.about_action.triggered.connect(self.show_about)

        for stage in STAGE_NAMES:
            sv = v.stage_views[stage]
            self._refresh_params(stage)

            sv["configure_btn"].clicked.connect(lambda _, s=stage: self.configure_parameters(s))
            sv["param_filter"].textChanged.connect(
                lambda text, s=stage: self._filter_params(s, text))
            sv["add_note_btn"].clicked.connect(lambda _, s=stage: self.add_note_tab(s))
            sv["rename_note_btn"].clicked.connect(lambda _, s=stage: self.rename_note_tab(s))
            sv["delete_note_btn"].clicked.connect(lambda _, s=stage: self.delete_note_tab(s))
            sv["upload_btn"].clicked.connect(lambda _, s=stage: self.upload_image(s))
            sv["view_btn"].clicked.connect(lambda _, s=stage: self.view_images(s))
            sv["complete_btn"].clicked.connect(lambda _, s=stage: self.complete_stage(s))
            sv["detach_btn"].clicked.connect(lambda _, s=stage: self.detach_stage(s))
            sv["img_list"].files_dropped.connect(
                lambda files, s=stage: self._handle_image_drop(files, s))
            sv["img_list"].itemDoubleClicked.connect(lambda _, s=stage: self.view_images(s))
            sv["review_cb"].toggled.connect(self.trigger_autosave)
            sv["notes_tabs"].currentChanged.connect(lambda _, s=stage: self._update_word_count(s))

            stage_data = self.model.data.stages[stage]
            if is_loaded:
                for note_name, note in stage_data.notes.items():
                    self._create_note_editor(stage, note_name, note.get("content", ""))
                sv["review_cb"].setChecked(stage_data.review_state)
                self._refresh_image_list(stage)
            else:
                self.add_note_tab(stage, f"{stage} Notes")

        self._update_stage_status()
        self._update_project_images()
        self._update_doc_summary()

        dv = v.doc_view
        dv["change_img_btn"].clicked.connect(self.change_project_image)
        dv["edit_desc_btn"].clicked.connect(self.edit_project_description)
        dv["generate_btn"].clicked.connect(self.generate_report)

        tv = v.tool_view
        tv["tools_list"].currentRowChanged.connect(self.load_tool_ui)
        tv["tool_filter"].textChanged.connect(self._filter_tools)
        tv["import_tool_btn"].clicked.connect(self.import_tool)
        tv["remove_tool_btn"].clicked.connect(self.remove_tool)
        self._refresh_tools_list()

        self._loading = False
        self._dirty = False
        v.status_bar.showMessage(
            "Project loaded." if is_loaded else "Project created.", 3000)

    def _on_close(self, event):
        if not self.view.project_ui_ready or not self._dirty:
            event.accept()
            return
        reply = QMessageBox.question(
            self.view, "Unsaved Changes",
            "This project has unsaved changes. Save before closing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if reply == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return
        if reply == QMessageBox.StandardButton.Save:
            self.autosave_timer.stop()
            try:
                self._sync_ui_to_model()
                self.model.save_project()
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self.view, "Error", f"Failed to save: {exc}")
                event.ignore()
                return
        event.accept()

    # --------------------------------------------------------------- palette
    def show_command_palette(self):
        commands = {
            "Save Project": self.save_project,
            "Export to Overleaf (ZIP)": self.generate_report,
            "Import Tool Script": self.import_tool,
            "Export Parameter Configuration": self.export_params,
            "Import Parameter Configuration": self.import_params,
            "Toggle Tools Panel": lambda: self.view.tools_dock.setVisible(
                not self.view.tools_dock.isVisible()),
            "Toggle Light/Dark Theme": self.toggle_theme,
            "Edit Project Description": self.edit_project_description,
            "Keyboard Shortcuts": self.show_shortcuts,
        }
        for i, name in enumerate((*STAGE_NAMES, "Documentation")):
            commands[f"Go to: {name}"] = lambda idx=i: self.view.sidebar_list.setCurrentRow(idx)
        for stage in STAGE_NAMES:
            commands[f"Configure Parameters: {stage}"] = \
                lambda s=stage: self.configure_parameters(s)
        for i, tool in enumerate(self.model.data.tools):
            commands[f"Run Tool: {tool['name']}"] = lambda idx=i: self._focus_tool(idx)

        CommandPalette(self.view, commands).exec()

    def _focus_tool(self, idx):
        self.view.tools_dock.show()
        self.view.tools_dock.raise_()
        self.view.tool_view["tool_filter"].clear()
        self.view.tool_view["tools_list"].setCurrentRow(idx)

    def show_shortcuts(self):
        QMessageBox.information(self.view, "Keyboard Shortcuts", (
            "Ctrl+S\t\tSave project\n"
            "Ctrl+E\t\tExport to Overleaf (ZIP)\n"
            "Ctrl+T\t\tImport tool script\n"
            "Ctrl+Shift+P\tCommand palette\n"
            "Ctrl+Shift+T\tToggle light/dark theme\n"
            "Ctrl+Q\t\tQuit\n"
            "F1\t\tThis help\n\n"
            "Images can be dragged straight onto a stage's image list."
        ))

    def show_about(self):
        QMessageBox.about(self.view, "About UAV Design Organizer", (
            "<b>UAV Design Organizer</b><br><br>"
            "A stage-gated design record for fixed wing and multirotor aircraft, "
            "with an importable Python tool system and LaTeX/Overleaf export.<br><br>"
            "Tool scripts define <tt>TOOL_METADATA</tt> and a <tt>run(inputs)</tt> function."
        ))

    def toggle_theme(self):
        names = list(THEMES)
        next_name = names[(names.index(self.theme_name) + 1) % len(names)]
        self._apply_theme(next_name)

    def _apply_theme(self, name, announce=True):
        app = QApplication.instance()
        if app is None:
            return
        self.theme_name = name
        apply_theme(app, name)
        if announce and self.view.project_ui_ready:
            self.view.status_bar.showMessage(f"Switched to {name} theme.", 2000)

    # -------------------------------------------------------------- autosave
    def trigger_autosave(self, *_):
        if self._loading:
            return
        self._dirty = True
        self.autosave_timer.start(AUTOSAVE_DELAY_MS)

    def _auto_save(self):
        try:
            self._sync_ui_to_model()
            self.model.save_project()
            self._dirty = False
            self._update_stage_status()
            self._update_doc_summary()
            self.view.status_bar.showMessage("Auto-saved.", 2000)
        except (OSError, ValueError) as exc:
            self.view.status_bar.showMessage(f"Auto-save failed: {exc}", 5000)

    def save_project(self):
        self.autosave_timer.stop()
        try:
            self._sync_ui_to_model()
            self.model.save_project()
            self._dirty = False
            self._update_stage_status()
            self._update_doc_summary()
            self._remember_project(self.model.json_path)
            self.view.status_bar.showMessage("Project saved.", 3000)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self.view, "Error", f"Failed to save project:\n{exc}")

    def _sync_ui_to_model(self):
        for stage_name, sv in self.view.stage_views.items():
            stage_data = self.model.data.stages[stage_name]
            for name, line_edit in sv["param_widgets"].items():
                stage_data.parameters[name] = line_edit.text()
            for note_name, editor in sv["note_editors"].items():
                if note_name in stage_data.notes:
                    stage_data.notes[note_name]["content"] = editor.toPlainText()
            stage_data.review_state = sv["review_cb"].isChecked()

    # ------------------------------------------------------------- status UI
    def _update_stage_status(self):
        for stage in STAGE_NAMES:
            stage_data = self.model.data.stages[stage]
            ratio = stage_data.completion_ratio()
            self.view.set_stage_status(stage, stage_data.completed, ratio)

            sv = self.view.stage_views[stage]
            required = len(stage_data.required_names())
            filled = int(round(ratio * required))
            sv["status_label"].setText(
                "Stage complete" if stage_data.completed
                else f"{filled}/{required} required parameters")

            self.view.doc_view["doc_include"][stage].setEnabled(stage_data.completed)
            if not stage_data.completed:
                self.view.doc_view["doc_include"][stage].setChecked(False)

        overall = int(self.model.overall_progress() * 100)
        self.view.progress_label.setText(f"Overall progress: {overall}%")

    def _update_doc_summary(self):
        dv = self.view.doc_view
        data = self.model.data
        dv["doc_summary_label"].setText(data.summary or "No summary set.")

        images = sum(len(s.images) for s in data.stages.values())
        notes = sum(len(s.notes) for s in data.stages.values())
        params = sum(1 for s in data.stages.values() for v in s.parameters.values()
                     if str(v).strip())
        dv["doc_summary_stats"].setText(
            f"Author: {data.author or '—'}\n"
            f"Parameters filled: {params}\n"
            f"Notes: {notes}\n"
            f"Images: {images}\n"
            f"Tools: {len(data.tools)}\n\n"
            f"Project folder:\n{self.model.project_dir}")

    def _update_project_images(self):
        label = self.view.doc_view["doc_proj_img_label"]
        if not self.model.data.image:
            self.view.proj_img_label.clear()
            label.setText("No project image set")
            return

        img_path = self.model.resolve_path(self.model.data.image)
        if not os.path.exists(img_path):
            self.view.proj_img_label.clear()
            label.setText("Project image file is missing")
            return

        pixmap = QPixmap(img_path)
        if pixmap.isNull():
            label.setText("Project image could not be read")
            return

        smooth = Qt.TransformationMode.SmoothTransformation
        keep = Qt.AspectRatioMode.KeepAspectRatio
        self.view.proj_img_label.setPixmap(pixmap.scaled(170, 170, keep, smooth))
        label.setText("")
        label.setPixmap(pixmap.scaled(420, 420, keep, smooth))

    # ------------------------------------------------------------ parameters
    def _refresh_params(self, stage_name):
        sv = self.view.stage_views[stage_name]
        layout = sv["param_layout"]
        self.view.clear_layout(layout)

        sv["param_widgets"] = {}
        sv["param_rows"] = {}
        stage_data = self.model.data.stages[stage_name]

        for param in stage_data.parameters_config:
            name = param["name"]
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 6)
            row_layout.setSpacing(3)

            label = QLabel(f"{name} *" if param.get("required") else name)
            if param.get("required"):
                set_role(label, "required")
            row_layout.addWidget(label)

            line_edit = QLineEdit()
            line_edit.setText(str(stage_data.parameters.get(name, "")))
            if param.get("unit"):
                line_edit.setPlaceholderText(str(param["unit"]))
            line_edit.textChanged.connect(self.trigger_autosave)
            row_layout.addWidget(line_edit)

            layout.addWidget(row)
            sv["param_widgets"][name] = line_edit
            sv["param_rows"][name] = row

        layout.addStretch()
        self._filter_params(stage_name, sv["param_filter"].text())

    def _filter_params(self, stage_name, text):
        text = text.strip().lower()
        for name, row in self.view.stage_views[stage_name]["param_rows"].items():
            row.setVisible(not text or text in name.lower())

    def configure_parameters(self, stage_name):
        dialog = QDialog(self.view)
        dialog.setWindowTitle(f"Configure Parameters — {stage_name}")
        dialog.resize(480, 420)

        layout = QVBoxLayout(dialog)
        layout.addWidget(set_role(QLabel(
            "Parameters marked required must be filled before the stage can be completed."),
            "subtle"))

        listbox = QListWidget()
        # Work on a copy so Cancel really cancels.
        config = [dict(p) for p in self.model.data.stages[stage_name].parameters_config]

        def repopulate(select_row=None):
            listbox.clear()
            for param in config:
                suffix = " (required)" if param.get("required") else ""
                listbox.addItem(f"{param['name']}{suffix}")
            if select_row is not None and 0 <= select_row < listbox.count():
                listbox.setCurrentRow(select_row)

        repopulate()
        layout.addWidget(listbox)

        def on_add():
            name, ok = QInputDialog.getText(dialog, "Add Parameter", "Parameter name:")
            name = name.strip() if ok else ""
            if not name:
                return
            if any(p["name"] == name for p in config):
                QMessageBox.warning(dialog, "Duplicate", "A parameter with that name exists.")
                return
            reply = QMessageBox.question(
                dialog, "Required?", f"Is '{name}' required to complete the stage?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            config.append({"name": name,
                           "required": reply == QMessageBox.StandardButton.Yes})
            repopulate(len(config) - 1)

        def on_toggle_required():
            row = listbox.currentRow()
            if row >= 0:
                config[row]["required"] = not config[row].get("required")
                repopulate(row)

        def on_remove():
            row = listbox.currentRow()
            if row < 0:
                return
            name = config[row]["name"]
            if QMessageBox.question(
                    dialog, "Remove Parameter",
                    f"Remove '{name}'? Its current value will be discarded.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) != QMessageBox.StandardButton.Yes:
                return
            del config[row]
            repopulate(min(row, len(config) - 1))

        def on_move(delta):
            row = listbox.currentRow()
            new_row = row + delta
            if row < 0 or not 0 <= new_row < len(config):
                return
            config[row], config[new_row] = config[new_row], config[row]
            repopulate(new_row)

        btn_layout = QHBoxLayout()
        for text, handler in (("Add…", on_add),
                              ("Toggle Required", on_toggle_required),
                              ("Remove", on_remove),
                              ("↑", lambda: on_move(-1)),
                              ("↓", lambda: on_move(1))):
            btn = QPushButton(text)
            btn.clicked.connect(handler)
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(dialog.reject)

        def on_accept():
            stage_data = self.model.data.stages[stage_name]
            kept = {p["name"] for p in config}
            # Drop values whose parameter no longer exists.
            stage_data.parameters = {k: v for k, v in stage_data.parameters.items()
                                     if k in kept}
            stage_data.parameters_config = config
            dialog.accept()
            self._refresh_params(stage_name)
            self._update_stage_status()
            self.trigger_autosave()

        buttons.accepted.connect(on_accept)
        layout.addWidget(buttons)
        dialog.exec()

    def export_params(self):
        config_data = {
            "version": "1.0",
            "stages": {name: stage.parameters_config
                       for name, stage in self.model.data.stages.items()},
        }
        file_path, _ = QFileDialog.getSaveFileName(
            self.view, "Export Parameter Configuration", "parameters.json", "JSON (*.json)")
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            self.view.status_bar.showMessage("Parameter configuration exported.", 3000)
        except OSError as exc:
            QMessageBox.critical(self.view, "Error", f"Export failed:\n{exc}")

    def import_params(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.view, "Import Parameter Configuration", "", "JSON (*.json)")
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self.view, "Error", f"Import failed:\n{exc}")
            return

        stages = config_data.get("stages")
        if not isinstance(stages, dict):
            QMessageBox.warning(self.view, "Invalid File",
                                "That file does not contain a 'stages' configuration.")
            return

        for stage_name, entries in stages.items():
            if stage_name in self.model.data.stages and isinstance(entries, list):
                self.model.data.stages[stage_name].parameters_config = entries
                self._refresh_params(stage_name)

        self._update_stage_status()
        self.trigger_autosave()
        self.view.status_bar.showMessage("Parameter configuration imported.", 3000)

    # ----------------------------------------------------------------- notes
    def add_note_tab(self, stage_name, name=None):
        stage_data = self.model.data.stages[stage_name]
        if not name:
            name, ok = QInputDialog.getText(self.view, "New Note", "Note name:")
            name = name.strip() if ok else ""
            if not name:
                return
        if name in stage_data.notes:
            QMessageBox.warning(self.view, "Duplicate Note",
                                f"A note called '{name}' already exists in this stage.")
            return

        stage_data.notes[name] = {
            "file": self.model.note_filename(stage_name, name),
            "content": "",
        }
        self._create_note_editor(stage_name, name, "")
        self.trigger_autosave()

    def _create_note_editor(self, stage_name, name, content):
        sv = self.view.stage_views[stage_name]
        editor = QTextEdit()
        editor.setPlainText(content)
        editor.setAcceptRichText(False)
        editor.setTabStopDistance(28)
        editor.textChanged.connect(self.trigger_autosave)
        editor.textChanged.connect(lambda s=stage_name: self._update_word_count(s))

        index = sv["notes_tabs"].addTab(editor, name)
        sv["note_editors"][name] = editor
        sv["notes_tabs"].setCurrentIndex(index)
        self._update_word_count(stage_name)

    def _update_word_count(self, stage_name):
        sv = self.view.stage_views[stage_name]
        editor = sv["notes_tabs"].currentWidget()
        if isinstance(editor, QTextEdit):
            text = editor.toPlainText()
            sv["word_count_label"].setText(f"{len(text.split())} words · {len(text)} chars")
        else:
            sv["word_count_label"].setText("")

    def _current_note(self, stage_name):
        sv = self.view.stage_views[stage_name]
        index = sv["notes_tabs"].currentIndex()
        if index < 0:
            return None, -1
        return sv["notes_tabs"].tabText(index), index

    def rename_note_tab(self, stage_name):
        sv = self.view.stage_views[stage_name]
        old_name, index = self._current_note(stage_name)
        if index < 0:
            return

        new_name, ok = QInputDialog.getText(self.view, "Rename Note", "Note name:", text=old_name)
        new_name = new_name.strip() if ok else ""
        if not new_name or new_name == old_name:
            return

        stage_data = self.model.data.stages[stage_name]
        if new_name in stage_data.notes:
            QMessageBox.warning(self.view, "Duplicate Note",
                                f"A note called '{new_name}' already exists.")
            return

        content = sv["note_editors"][old_name].toPlainText()
        self.model.delete_note(stage_name, old_name)
        stage_data.notes[new_name] = {
            "file": self.model.note_filename(stage_name, new_name),
            "content": content,
        }
        sv["note_editors"][new_name] = sv["note_editors"].pop(old_name)
        sv["notes_tabs"].setTabText(index, new_name)
        self.trigger_autosave()

    def delete_note_tab(self, stage_name):
        sv = self.view.stage_views[stage_name]
        note_name, index = self._current_note(stage_name)
        if index < 0:
            return

        reply = QMessageBox.question(
            self.view, "Delete Note",
            f"Delete note '{note_name}'? Its markdown file will be removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.model.delete_note(stage_name, note_name)
        sv["note_editors"].pop(note_name, None)
        widget = sv["notes_tabs"].widget(index)
        sv["notes_tabs"].removeTab(index)
        if widget is not None:
            widget.deleteLater()
        self._update_word_count(stage_name)
        self.trigger_autosave()

    # ---------------------------------------------------------------- images
    def _handle_image_drop(self, files, stage_name):
        added = 0
        for path in files:
            if not os.path.exists(path):
                continue
            caption, ok = QInputDialog.getText(
                self.view, "Image Caption",
                f"Caption for {os.path.basename(path)}:",
                text=os.path.splitext(os.path.basename(path))[0])
            if not ok:
                continue
            try:
                stored = self.model.import_asset(path)
            except OSError as exc:
                QMessageBox.critical(self.view, "Error", f"Could not copy image:\n{exc}")
                continue
            self.model.data.stages[stage_name].images.append(
                {"path": stored, "caption": caption})
            added += 1

        if added:
            self._refresh_image_list(stage_name)
            self._update_doc_summary()
            self.trigger_autosave()
            self.view.status_bar.showMessage(
                f"Added {added} image{'s' if added != 1 else ''}.", 3000)

    def upload_image(self, stage_name):
        files, _ = QFileDialog.getOpenFileNames(
            self.view, "Select Images", "", IMAGE_FILTER)
        if files:
            self._handle_image_drop(files, stage_name)

    def _refresh_image_list(self, stage_name):
        sv = self.view.stage_views[stage_name]
        sv["img_list"].clear()
        for img in self.model.data.stages[stage_name].images:
            caption = img.get("caption") or os.path.basename(img.get("path", ""))
            item = QListWidgetItem(caption or "Untitled image")
            item.setToolTip(img.get("path", ""))
            sv["img_list"].addItem(item)

    def view_images(self, stage_name):
        images = self.model.data.stages[stage_name].images
        dialog = QDialog(self.view)
        dialog.setWindowTitle(f"{stage_name} Images")
        dialog.resize(760, 620)

        layout = QVBoxLayout(dialog)
        tree = QTreeWidget()
        tree.setHeaderLabels(["Caption", "File"])
        tree.setMaximumHeight(180)
        layout.addWidget(tree)

        image_label = QLabel("Select an image to preview it.")
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setMinimumHeight(320)
        set_role(image_label, "dropzone")
        layout.addWidget(image_label, 1)

        def repopulate(select=0):
            tree.clear()
            for i, img in enumerate(images):
                item = QTreeWidgetItem([img.get("caption", ""),
                                        os.path.basename(img.get("path", ""))])
                item.setData(0, Qt.ItemDataRole.UserRole, i)
                tree.addTopLevelItem(item)
            if 0 <= select < tree.topLevelItemCount():
                tree.setCurrentItem(tree.topLevelItem(select))
            else:
                image_label.setPixmap(QPixmap())
                image_label.setText("No images in this stage yet.")

        def show_image():
            current = tree.currentItem()
            if not current:
                return
            img = images[current.data(0, Qt.ItemDataRole.UserRole)]
            path = self.model.resolve_path(img.get("path", ""))
            pixmap = QPixmap(path) if os.path.exists(path) else QPixmap()
            if pixmap.isNull():
                image_label.setPixmap(QPixmap())
                image_label.setText(f"Image file not found:\n{img.get('path', '')}")
                return
            image_label.setText("")
            image_label.setPixmap(pixmap.scaled(
                image_label.width() - 20, image_label.height() - 20,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

        tree.itemSelectionChanged.connect(show_image)

        def on_edit_caption():
            current = tree.currentItem()
            if not current:
                return
            idx = current.data(0, Qt.ItemDataRole.UserRole)
            caption, ok = QInputDialog.getText(dialog, "Edit Caption", "Caption:",
                                               text=images[idx].get("caption", ""))
            if ok:
                images[idx]["caption"] = caption.strip()
                repopulate(idx)
                self._refresh_image_list(stage_name)
                self.trigger_autosave()

        def on_delete():
            current = tree.currentItem()
            if not current:
                return
            idx = current.data(0, Qt.ItemDataRole.UserRole)
            if QMessageBox.question(
                    dialog, "Remove Image",
                    "Remove this image from the stage?\n"
                    "(The file stays in the project's images folder.)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) != QMessageBox.StandardButton.Yes:
                return
            del images[idx]
            repopulate(min(idx, len(images) - 1))
            self._refresh_image_list(stage_name)
            self._update_doc_summary()
            self.trigger_autosave()

        btn_layout = QHBoxLayout()
        edit_btn = QPushButton("Edit Caption…")
        edit_btn.clicked.connect(on_edit_caption)
        del_btn = QPushButton("Remove Image")
        del_btn.setProperty("danger", True)
        del_btn.clicked.connect(on_delete)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        repopulate()
        dialog.exec()

    # ---------------------------------------------------------------- stages
    def complete_stage(self, stage):
        sv = self.view.stage_views[stage]
        stage_data = self.model.data.stages[stage]

        missing = [name for name in stage_data.required_names()
                   if not sv["param_widgets"].get(name, QLineEdit()).text().strip()]
        if missing:
            QMessageBox.warning(
                self.view, "Incomplete Stage",
                "These required parameters are still empty:\n\n• " + "\n• ".join(missing))
            return
        if not sv["review_cb"].isChecked():
            QMessageBox.warning(self.view, "Incomplete Stage",
                                "Confirm the design review before completing this stage.")
            return

        stage_data.completed = True
        self.view.doc_view["doc_include"][stage].setChecked(True)
        self._update_stage_status()
        self.view.status_bar.showMessage(f"{stage} stage completed.", 4000)
        self.trigger_autosave()

    def detach_stage(self, stage_name):
        sv = self.view.stage_views[stage_name]
        widget = sv["widget"]

        existing = self.detached_stages.get(stage_name)
        if existing:
            existing.raise_()
            existing.activateWindow()
            return

        index = self.view.central_stack.indexOf(widget)
        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        label = set_role(QLabel(f"{stage_name} is open in a separate window."), "subtle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(label)

        reattach_btn = QPushButton("Bring Back")
        reattach_row = QHBoxLayout()
        reattach_row.addStretch()
        reattach_row.addWidget(reattach_btn)
        reattach_row.addStretch()
        placeholder_layout.addLayout(reattach_row)

        self.view.central_stack.removeWidget(widget)
        self.view.central_stack.insertWidget(index, placeholder)
        if self.view.sidebar_list.currentRow() == index:
            self.view.central_stack.setCurrentIndex(index)

        detached_win = QDialog(self.view)
        detached_win.setWindowTitle(f"UAV Design Organizer — {stage_name}")
        detached_win.resize(900, 700)
        win_layout = QVBoxLayout(detached_win)
        win_layout.addWidget(widget)
        widget.show()

        def reattach():
            # Reparent before the dialog is destroyed, or Qt deletes the stage.
            widget.setParent(None)
            slot = self.view.central_stack.indexOf(placeholder)
            if slot >= 0:
                self.view.central_stack.removeWidget(placeholder)
                self.view.central_stack.insertWidget(slot, widget)
            else:
                slot = self.view.central_stack.addWidget(widget)
            placeholder.deleteLater()
            sv["detach_btn"].setVisible(True)
            self.detached_stages.pop(stage_name, None)
            if self.view.sidebar_list.currentRow() == slot:
                self.view.central_stack.setCurrentIndex(slot)

        def on_close(event):
            reattach()
            event.accept()
            detached_win.deleteLater()

        reattach_btn.clicked.connect(detached_win.close)
        detached_win.closeEvent = on_close
        self.detached_stages[stage_name] = detached_win
        detached_win.show()
        sv["detach_btn"].setVisible(False)

    # --------------------------------------------------------- documentation
    def change_project_image(self):
        file, _ = QFileDialog.getOpenFileName(self.view, "Select Project Image", "", IMAGE_FILTER)
        if not file:
            return
        try:
            self.model.data.image = self.model.import_asset(file)
        except OSError as exc:
            QMessageBox.critical(self.view, "Error", f"Could not copy image:\n{exc}")
            return
        self._update_project_images()
        self.trigger_autosave()

    def edit_project_description(self):
        dialog = QDialog(self.view)
        dialog.setWindowTitle("Edit Project Description")
        dialog.setMinimumWidth(480)

        layout = QVBoxLayout(dialog)
        name_edit = QLineEdit(self.model.data.name)
        author_edit = QLineEdit(self.model.data.author)
        summary_edit = QTextEdit()
        summary_edit.setPlainText(self.model.data.summary)
        summary_edit.setAcceptRichText(False)

        layout.addWidget(QLabel("Name:"))
        layout.addWidget(name_edit)
        layout.addWidget(QLabel("Author:"))
        layout.addWidget(author_edit)
        layout.addWidget(QLabel("Summary:"))
        layout.addWidget(summary_edit)
        layout.addWidget(set_role(QLabel(
            "Renaming the project updates the report only; the folder and file names stay put."),
            "subtle"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(dialog.reject)

        def on_accept():
            name = name_edit.text().strip()
            if not name:
                QMessageBox.warning(dialog, "Incomplete", "Project name is required.")
                return
            self.model.update_project_description(
                name, author_edit.text().strip(), summary_edit.toPlainText())
            self.view.setWindowTitle(f"UAV Design Organizer — {name}")
            self.view.project_name_label.setText(name)
            self.view.project_author_label.setText(self.model.data.author)
            self._update_doc_summary()
            dialog.accept()
            self.trigger_autosave()

        buttons.accepted.connect(on_accept)
        layout.addWidget(buttons)
        dialog.exec()

    def generate_report(self):
        self._sync_ui_to_model()

        dv = self.view.doc_view
        selected = [s for s in STAGE_NAMES if dv["doc_include"][s].isChecked()]
        if not selected:
            QMessageBox.warning(
                self.view, "No Stages Selected",
                "Select at least one completed stage to include in the report.")
            self.view.sidebar_list.setCurrentRow(len(STAGE_NAMES))
            return

        options = {key: cb.isChecked() for key, cb in dv["doc_options"].items()}

        try:
            self.view.status_bar.showMessage("Building Overleaf package…")
            QApplication.processEvents()
            export_path = generate_overleaf_zip(self.model, selected, options)
        except Exception as exc:
            self.view.status_bar.clearMessage()
            QMessageBox.critical(self.view, "Export Failed", str(exc))
            return

        self.view.status_bar.showMessage(f"Exported to {export_path}", 6000)
        box = QMessageBox(self.view)
        box.setWindowTitle("Export Complete")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("Overleaf package created.")
        box.setInformativeText(export_path)
        open_btn = box.addButton("Show in Folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            webbrowser.open(f"file:///{os.path.dirname(export_path)}")

    # ----------------------------------------------------------------- tools
    def import_tool(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.view, "Import Tool Script", "", "Python Files (*.py)")
        if not file_path:
            return

        try:
            _, metadata = ToolManager.load_tool_from_file(file_path)
        except ToolError as exc:
            QMessageBox.critical(self.view, "Invalid Tool", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self.view, "Error", f"Failed to import tool:\n{exc}")
            return

        tools_dir = os.path.join(self.model.project_dir, "Tools")
        os.makedirs(tools_dir, exist_ok=True)
        # Ship uavlib alongside so the tool still runs if the folder is moved.
        try:
            ToolManager.sync_library(self.model.project_dir)
        except OSError:
            pass  # Tools still run in-app from the bundled copy.
        filename = os.path.basename(file_path)
        dest_path = os.path.join(tools_dir, filename)

        if (os.path.exists(dest_path)
                and os.path.abspath(file_path) != os.path.abspath(dest_path)):
            if QMessageBox.question(
                    self.view, "Replace Tool",
                    f"'{filename}' already exists in this project. Replace it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) != QMessageBox.StandardButton.Yes:
                return

        try:
            if os.path.abspath(file_path) != os.path.abspath(dest_path):
                shutil.copy2(file_path, dest_path)
        except OSError as exc:
            QMessageBox.critical(self.view, "Error", f"Could not copy tool:\n{exc}")
            return

        entry = {
            "name": metadata["name"],
            "description": metadata["description"],
            "category": metadata.get("category", ""),
            "inputs": metadata["inputs"],
            "filename": filename,
        }
        self.model.data.tools = [t for t in self.model.data.tools
                                 if t.get("filename") != filename]
        self.model.data.tools.append(entry)
        self.model.data.tools.sort(
            key=lambda t: (t.get("category", "").lower(), t["name"].lower()))

        self._refresh_tools_list()
        self._update_doc_summary()
        self.view.status_bar.showMessage(f"Imported tool '{entry['name']}'.", 4000)
        self.trigger_autosave()

    def _refresh_tools_list(self):
        """List tools grouped under their declared category."""
        tv = self.view.tool_view
        tv["tools_list"].clear()
        # Row index in the widget maps to the index in model.data.tools, so
        # non-selectable headers must not shift that mapping -- instead the
        # category is shown on the item itself.
        last_category = None
        for tool in self.model.data.tools:
            category = tool.get("category", "")
            item = QListWidgetItem(tool["name"])
            tooltip = tool.get("description", "")
            if category:
                tooltip = f"{category}\n\n{tooltip}" if tooltip else category
                if category != last_category:
                    item.setText(f"{tool['name']}   ·   {category}")
                    last_category = category
            item.setToolTip(tooltip)
            item.setData(Qt.ItemDataRole.UserRole, category)
            tv["tools_list"].addItem(item)
        self._filter_tools(tv["tool_filter"].text())

    def _filter_tools(self, text):
        """Match the search against both the tool name and its category."""
        list_widget = self.view.tool_view["tools_list"]
        query = text.strip()
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            category = item.data(Qt.ItemDataRole.UserRole) or ""
            haystack = f"{item.text()} {category}"
            item.setHidden(not fuzzy_match(query, haystack))

    def remove_tool(self):
        tv = self.view.tool_view
        row = tv["tools_list"].currentRow()
        if row < 0 or row >= len(self.model.data.tools):
            return

        name = self.model.data.tools[row]["name"]
        if QMessageBox.question(
                self.view, "Remove Tool",
                f"Remove '{name}' from this project?\n"
                "(The script file stays in the project's Tools folder.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return

        del self.model.data.tools[row]
        self._refresh_tools_list()
        self.view.clear_layout(tv["tool_layout"])
        tv["tool_layout"].addWidget(set_role(QLabel("Select a tool to run it."), "subtle"))
        tv["tool_layout"].addStretch()
        self.current_tool_inputs = {}
        self.tool_output = None
        self._update_doc_summary()
        self.trigger_autosave()

    def get_all_project_parameters(self):
        self._sync_ui_to_model()
        params = {}
        for stage in STAGE_NAMES:
            for key, value in self.model.data.stages[stage].parameters.items():
                if str(value).strip():
                    params[f"[{stage}] {key}"] = value
        return params

    def load_tool_ui(self, index):
        if index < 0 or index >= len(self.model.data.tools):
            return

        tool_data = self.model.data.tools[index]
        tv = self.view.tool_view
        layout = tv["tool_layout"]
        self.view.clear_layout(layout)

        layout.addWidget(set_role(QLabel(tool_data["name"]), "heading"))

        if tool_data.get("description"):
            desc = set_role(QLabel(tool_data["description"]), "subtle")
            desc.setWordWrap(True)
            layout.addWidget(desc)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        self.current_tool_inputs = {}
        available = self.get_all_project_parameters()

        for spec in tool_data.get("inputs", []):
            layout.addWidget(self._build_tool_input(spec, available))

        run_btn = accent(QPushButton("Run Tool"))
        run_btn.setMinimumHeight(34)
        run_btn.clicked.connect(lambda: self.run_tool(tool_data, run_btn))
        layout.addWidget(run_btn)

        output_header = QHBoxLayout()
        output_header.addWidget(set_role(QLabel("Output"), "subtle"))
        output_header.addStretch()
        copy_btn = QPushButton("Copy")
        clear_btn = QPushButton("Clear")
        output_header.addWidget(copy_btn)
        output_header.addWidget(clear_btn)
        layout.addLayout(output_header)

        self.tool_output = QTextEdit()
        self.tool_output.setReadOnly(True)
        self.tool_output.setFont(monospace_font())
        self.tool_output.setMinimumHeight(200)
        self.tool_output.setPlaceholderText("Results appear here after running the tool.")
        layout.addWidget(self.tool_output, 1)

        # Charts and structured results are appended below the text output when
        # a tool produces them.
        self.tool_extras_layout = QVBoxLayout()
        layout.addLayout(self.tool_extras_layout)

        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self.tool_output.toPlainText()))
        clear_btn.clicked.connect(self._clear_tool_output)

    def _build_tool_input(self, spec, available):
        """One labelled input row, rendered according to its declared type."""
        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 6)
        row_layout.setSpacing(3)

        unit = spec.get("unit", "")
        label_text = spec.get("label", spec["key"])
        limits = []
        if spec.get("min") is not None:
            limits.append(f"min {spec['min']:g}")
        if spec.get("max") is not None:
            limits.append(f"max {spec['max']:g}")
        suffix = f"  ({unit})" if unit else ""
        label = QLabel(f"{label_text}{suffix}")
        if limits:
            label.setToolTip(", ".join(limits))
        row_layout.addWidget(label)

        kind = spec.get("type", "text")

        if kind == "choice":
            combo = QComboBox()
            combo.addItems(spec.get("choices", []))
            if spec.get("default") in spec.get("choices", []):
                combo.setCurrentText(spec["default"])
            if spec.get("help"):
                combo.setToolTip(spec["help"])
            row_layout.addWidget(combo)
            self.current_tool_inputs[spec["key"]] = combo
            return row

        field_row = QHBoxLayout()
        value_edit = QLineEdit()
        value_edit.setText(spec.get("default", ""))
        hint = unit or ("number" if kind == "number" else "value")
        if limits:
            hint = f"{hint}  ({', '.join(limits)})"
        value_edit.setPlaceholderText(hint)
        if spec.get("help"):
            value_edit.setToolTip(spec["help"])

        if kind == "file":
            browse_btn = QPushButton("Browse…")
            browse_btn.setMaximumWidth(90)
            browse_btn.clicked.connect(
                lambda _, edit=value_edit: self._browse_tool_file(edit))
            field_row.addWidget(value_edit, 1)
            field_row.addWidget(browse_btn)
        else:
            source_combo = QComboBox()
            source_combo.addItem("Manual")
            for param_key in available:
                source_combo.addItem(param_key)
            source_combo.setMaximumWidth(160)

            def on_source_changed(idx, combo=source_combo, edit=value_edit):
                if idx == 0:
                    edit.setReadOnly(False)
                else:
                    edit.setText(str(available.get(combo.currentText(), "")))
                    edit.setReadOnly(True)

            source_combo.currentIndexChanged.connect(on_source_changed)
            field_row.addWidget(source_combo)
            field_row.addWidget(value_edit, 1)

        row_layout.addLayout(field_row)
        self.current_tool_inputs[spec["key"]] = value_edit
        return row

    def _browse_tool_file(self, line_edit):
        start_dir = self.model.project_dir or ""
        file, _ = QFileDialog.getOpenFileName(self.view, "Select File", start_dir)
        if file:
            line_edit.setText(file)

    @staticmethod
    def _input_value(widget) -> str:
        return widget.currentText() if isinstance(widget, QComboBox) else widget.text()

    def _clear_tool_output(self):
        self.tool_output.clear()
        if getattr(self, "tool_extras_layout", None):
            self.view.clear_layout(self.tool_extras_layout)

    def run_tool(self, tool_data, run_btn=None):
        file_path = os.path.join(self.model.project_dir, "Tools", tool_data["filename"])
        try:
            tool_instance, _ = ToolManager.load_tool_from_file(file_path)
        except ToolError as exc:
            self.tool_output.setPlainText(str(exc))
            return
        except Exception as exc:
            self.tool_output.setPlainText(f"Failed to load tool: {exc}")
            return

        inputs = {key: self._input_value(widget)
                  for key, widget in self.current_tool_inputs.items()}
        self._clear_tool_output()
        self.tool_output.setPlainText("Running…")
        if run_btn:
            run_btn.setEnabled(False)

        worker = ToolWorker(tool_instance, inputs, parent=self.view)

        def on_success(result):
            self.tool_output.setPlainText(result.get("text", ""))
            self._show_tool_extras(result)
            if run_btn:
                run_btn.setEnabled(True)
            self.view.status_bar.showMessage(f"{tool_data['name']} finished.", 3000)

        def on_failure(message):
            self.tool_output.setPlainText(message)
            if run_btn:
                run_btn.setEnabled(True)

        worker.result_ready.connect(on_success)
        worker.failed.connect(on_failure)
        # Keep a reference until the thread ends, or Qt destroys a running QThread.
        worker.finished.connect(lambda: self.tool_workers.remove(worker)
                                if worker in self.tool_workers else None)
        worker.finished.connect(worker.deleteLater)
        self.tool_workers.append(worker)
        worker.start()
        self.view.status_bar.showMessage(f"Running {tool_data['name']}…", 2000)

    # ------------------------------------------------- tool charts & outputs
    def _show_tool_extras(self, result):
        """Render any charts and structured outputs a tool returned."""
        container = getattr(self, "tool_extras_layout", None)
        if container is None:
            return
        self.view.clear_layout(container)

        for figure in result.get("figures", []):
            container.addWidget(self._build_figure_widget(figure))

        outputs = result.get("outputs", {})
        if outputs:
            container.addWidget(self._build_outputs_widget(outputs))

    def _build_figure_widget(self, figure):
        group = QGroupBox(figure.get("title", "Figure"))
        group_layout = QVBoxLayout(group)

        pixmap = QPixmap()
        pixmap.loadFromData(figure["png"])

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if pixmap.isNull():
            image_label.setText("Chart could not be rendered.")
        else:
            image_label.setPixmap(pixmap.scaledToWidth(
                420, Qt.TransformationMode.SmoothTransformation))
        group_layout.addWidget(image_label)

        button_row = QHBoxLayout()
        attach_combo = QComboBox()
        attach_combo.addItems(STAGE_NAMES)
        attach_btn = QPushButton("Attach to stage images")
        attach_btn.clicked.connect(
            lambda: self._attach_figure(figure, attach_combo.currentText(), attach_btn))
        save_btn = QPushButton("Save as…")
        save_btn.clicked.connect(lambda: self._save_figure(figure))
        button_row.addWidget(attach_combo)
        button_row.addWidget(attach_btn)
        button_row.addWidget(save_btn)
        button_row.addStretch()
        group_layout.addLayout(button_row)
        return group

    def _attach_figure(self, figure, stage_name, button=None):
        """Write a chart into the project images and link it to a stage.

        Attached charts flow straight into the Overleaf export alongside
        photographs, which is the point of generating them here.
        """
        title = figure.get("title", "Figure")
        try:
            os.makedirs(self.model.images_dir, exist_ok=True)
            base = sanitize_filename(f"{title}") or "figure"
            temp_path = os.path.join(self.model.images_dir, f"{base}.png")
            counter = 1
            while os.path.exists(temp_path):
                temp_path = os.path.join(self.model.images_dir, f"{base}_{counter}.png")
                counter += 1
            with open(temp_path, "wb") as handle:
                handle.write(figure["png"])
        except OSError as exc:
            QMessageBox.critical(self.view, "Error", f"Could not save chart:\n{exc}")
            return

        stored = f"{IMAGES_DIRNAME}/{os.path.basename(temp_path)}"
        self.model.data.stages[stage_name].images.append(
            {"path": stored, "caption": title})
        self._refresh_image_list(stage_name)
        self._update_doc_summary()
        self.trigger_autosave()
        if button:
            button.setText("Attached ✓")
        self.view.status_bar.showMessage(f"Chart attached to {stage_name}.", 3000)

    def _save_figure(self, figure):
        default = sanitize_filename(figure.get("title", "figure")) + ".png"
        path, _ = QFileDialog.getSaveFileName(
            self.view, "Save Chart", default, "PNG Image (*.png)")
        if not path:
            return
        try:
            with open(path, "wb") as handle:
                handle.write(figure["png"])
            self.view.status_bar.showMessage(f"Chart saved to {path}", 4000)
        except OSError as exc:
            QMessageBox.critical(self.view, "Error", f"Could not save chart:\n{exc}")

    def _build_outputs_widget(self, outputs):
        """Structured results, with a control to write them into a stage."""
        group = QGroupBox("Computed Values")
        group_layout = QVBoxLayout(group)

        for name, spec in outputs.items():
            value = spec.get("value", "")
            unit = spec.get("unit", "")
            text = f"{value:,.4g}" if isinstance(value, (int, float)) else str(value)
            row = QHBoxLayout()
            row.addWidget(set_role(QLabel(f"{name}:"), "subtle"))
            row.addStretch()
            row.addWidget(QLabel(f"{text} {unit}".strip()))
            group_layout.addLayout(row)

        button_row = QHBoxLayout()
        stage_combo = QComboBox()
        stage_combo.addItems(STAGE_NAMES)
        save_btn = QPushButton("Save to stage parameters")
        save_btn.setToolTip("Adds these as parameters on the selected stage, "
                            "so other tools can read them.")
        save_btn.clicked.connect(
            lambda: self._save_outputs_to_stage(outputs, stage_combo.currentText()))
        button_row.addWidget(stage_combo)
        button_row.addWidget(save_btn)
        button_row.addStretch()
        group_layout.addLayout(button_row)
        return group

    def _save_outputs_to_stage(self, outputs, stage_name):
        """Write tool results back into a stage's parameters.

        Closes the loop: parameters already feed into tools, and results can now
        feed back out without retyping.
        """
        stage = self.model.data.stages[stage_name]
        existing = {p["name"] for p in stage.parameters_config}
        added = 0

        for name, spec in outputs.items():
            value = spec.get("value", "")
            unit = spec.get("unit", "")
            text = f"{value:.6g}" if isinstance(value, (int, float)) else str(value)
            if unit:
                text = f"{text} {unit}"
            if name not in existing:
                stage.parameters_config.append(
                    {"name": name, "required": False, "unit": unit})
                existing.add(name)
                added += 1
            stage.parameters[name] = text

        self._refresh_params(stage_name)
        self._update_stage_status()
        self.trigger_autosave()
        self.view.status_bar.showMessage(
            f"Saved {len(outputs)} value(s) to {stage_name}"
            + (f" ({added} new parameter(s))." if added else "."), 4000)
