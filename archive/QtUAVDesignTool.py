import sys
import os
import json
import shutil
import datetime
import subprocess

# PyQt6 Imports
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QLineEdit, QTextEdit, QFileDialog, 
                             QMessageBox, QTabWidget, QCheckBox, QListWidget, QDialog,
                             QInputDialog, QTreeWidget, QTreeWidgetItem, QScrollArea,
                             QFormLayout, QDialogButtonBox, QFrame)
from PyQt6.QtGui import QPixmap, QAction
from PyQt6.QtCore import Qt

class UAVDesignTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UAV Design Organizer")
        self.setGeometry(100, 100, 800, 600)

        self.project_data = {
            "name": "",
            "author": "",
            "summary": "",
            "image": None,
            "stages": {
                "Conceptual": {"parameters": {}, "images": [], "notes": {}, "completed": False, "review_state": False, "parameters_config": [
                    {"name": "Configuration Type", "required": True},
                    {"name": "Wing Type", "required": True},
                    {"name": "Tail Type", "required": True},
                    {"name": "Fuselage Geometry", "required": True},
                    {"name": "Engine Type", "required": True},
                    {"name": "Landing Gear Type", "required": True}
                ]},
                "Preliminary": {"parameters": {}, "images": [], "notes": {}, "completed": False, "review_state": False, "parameters_config": [
                    {"name": "Max Takeoff Weight (W_TO)", "required": True},
                    {"name": "Wing Area (S)", "required": True},
                    {"name": "Engine Thrust/Power (T/P)", "required": True},
                    {"name": "Autopilot Preliminary Data", "required": True}
                ]},
                "Detail": {"parameters": {}, "images": [], "notes": {}, "completed": False, "review_state": False, "parameters_config": [
                    {"name": "Wing Parameters", "required": True},
                    {"name": "Tail Parameters", "required": True},
                    {"name": "Fuselage Parameters", "required": True},
                    {"name": "Landing Gear Parameters", "required": True},
                    {"name": "Engine Parameters", "required": True},
                    {"name": "Autopilot Parameters", "required": True},
                    {"name": "Subsystems Parameters", "required": True}
                ]}
            }
        }
        self.completed_stages = {"Conceptual": False, "Preliminary": False, "Detail": False}
        self.project_dir = None
        self.proj_img_path = ""
        self.proj_img_label = None

        self.create_start_page()

    def create_start_page(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout()
        layout.addStretch()
        
        label = QLabel("Welcome to UAV Design Organizer")
        # PyQt6: Qt.AlignCenter -> Qt.AlignmentFlag.AlignCenter
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        
        load_btn = QPushButton("Load Project")
        load_btn.clicked.connect(self.load_project)
        layout.addWidget(load_btn)
        
        new_btn = QPushButton("New Project")
        new_btn.clicked.connect(self.new_project)
        layout.addWidget(new_btn)
        
        layout.addStretch()
        central_widget.setLayout(layout)

    def new_project(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("New Project")
        dialog.setModal(True)
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel("Project Name:"))
        name_edit = QLineEdit()
        layout.addWidget(name_edit)
        
        layout.addWidget(QLabel("Author:"))
        author_edit = QLineEdit()
        layout.addWidget(author_edit)
        
        layout.addWidget(QLabel("Summary:"))
        summary_edit = QTextEdit()
        summary_edit.setMaximumHeight(100)
        layout.addWidget(summary_edit)
        
        layout.addWidget(QLabel("Optional Image:"))
        img_layout = QHBoxLayout()
        img_path_edit = QLineEdit()
        img_browse_btn = QPushButton("Browse")
        img_browse_btn.clicked.connect(lambda: self.browse_image(img_path_edit))
        img_layout.addWidget(img_path_edit)
        img_layout.addWidget(img_browse_btn)
        layout.addLayout(img_layout)
        
        create_btn = QPushButton("Create")
        create_btn.clicked.connect(lambda: self.create_project(dialog, name_edit.text(), 
                                                                author_edit.text(), 
                                                                summary_edit.toPlainText(),
                                                                img_path_edit.text()))
        layout.addWidget(create_btn)
        
        dialog.setLayout(layout)
        # PyQt6: exec_() -> exec()
        dialog.exec()

    def browse_image(self, line_edit):
        file, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Image Files (*.jpg *.png *.gif)")
        if file:
            line_edit.setText(file)

    def create_project(self, dialog, name, author, summary, img_path):
        if not name.strip():
            QMessageBox.warning(self, "Incomplete", "Project name required.")
            return
        
        self.project_data["name"] = name
        self.project_data["author"] = author
        self.project_data["summary"] = summary
        if img_path:
            self.project_data["image"] = os.path.basename(img_path)
            self.proj_img_path = img_path
        
        project_folder = QFileDialog.getExistingDirectory(self, "Select Project Folder")
        if not project_folder:
            return
        
        self.project_dir = os.path.join(project_folder, self.project_data["name"])
        os.makedirs(self.project_dir, exist_ok=True)
        
        # Copy project image
        if img_path:
            dst = os.path.join(self.project_dir, self.project_data["image"])
            shutil.copy(img_path, dst)
        
        # Create stage directories
        for stagename in ["Conceptual", "Preliminary", "Detail"]:
            os.makedirs(os.path.join(self.project_dir, stagename), exist_ok=True)
        
        # Save initial JSON
        json_path = os.path.join(self.project_dir, f"{self.project_data['name']}.json")
        with open(json_path, "w") as f:
            json.dump(self.project_data, f)
        
        dialog.accept()
        self.setup_main_ui()

    def setup_main_ui(self, is_loaded=False):
        self.setWindowTitle(f"UAV Design Organizer - {self.project_data['name']}")
        
        # Create menu bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        
        save_action = file_menu.addAction("Save Project")
        save_action.triggered.connect(self.save_project)
        
        file_menu.addSeparator()
        
        export_action = file_menu.addAction("Export Parameter Configuration")
        export_action.triggered.connect(self.export_parameter_config)
        
        import_action = file_menu.addAction("Import Parameter Configuration")
        import_action.triggered.connect(self.import_parameter_config)
        
        # Create central widget with tabs
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        self.create_tabs(is_loaded)
        
        # Lock tabs initially
        self.tab_widget.setTabEnabled(1, self.completed_stages["Conceptual"])
        self.tab_widget.setTabEnabled(2, self.completed_stages["Preliminary"])
        
        # Display project image
        if self.project_data["image"]:
            img_path = self.proj_img_path if self.proj_img_path else os.path.join(self.project_dir, self.project_data["image"])
            if os.path.exists(img_path):
                self.proj_img_label = QLabel()
                pixmap = QPixmap(img_path)
                # PyQt6: Qt.KeepAspectRatio -> Qt.AspectRatioMode.KeepAspectRatio
                # PyQt6: Qt.SmoothTransformation -> Qt.TransformationMode.SmoothTransformation
                self.proj_img_label.setPixmap(pixmap.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                # PyQt6: Qt.AlignRight | Qt.AlignBottom -> Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
                self.proj_img_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
                main_layout.addWidget(self.proj_img_label, alignment=Qt.AlignmentFlag.AlignRight)
        
        central_widget.setLayout(main_layout)

    def create_tabs(self, is_loaded):
        stages = ["Conceptual Design", "Preliminary Design", "Detail Design"]
        reviews = ["CDR", "PDR", "FDR"]
        
        for i, stage in enumerate(stages):
            stagename = stage.replace(" Design", "")
            
            tab = QWidget()
            layout = QVBoxLayout()
            
            # Parameters section
            layout.addWidget(QLabel("Parameters:"))
            
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            param_widget = QWidget()
            param_layout = QVBoxLayout()
            param_widget.setLayout(param_layout)
            scroll.setWidget(param_widget)
            scroll.setMaximumHeight(200)
            layout.addWidget(scroll)
            
            self.project_data["stages"][stagename]["param_layout"] = param_layout
            self.refresh_params(stagename)
            
            configure_btn = QPushButton("Configure Parameters")
            configure_btn.clicked.connect(lambda checked, s=stagename: self.configure_parameters(s))
            layout.addWidget(configure_btn)
            
            # Notes section
            layout.addWidget(QLabel("Notes:"))
            notes_tabs = QTabWidget()
            self.project_data["stages"][stagename]["notes_tabs"] = notes_tabs
            layout.addWidget(notes_tabs)
            
            if not is_loaded:
                default_name = f"{stagename} Notes"
                self.add_note_tab(stagename, default_name)
            
            add_note_btn = QPushButton("Add Note Tab")
            add_note_btn.clicked.connect(lambda checked, s=stagename: self.add_note_tab(s))
            layout.addWidget(add_note_btn)
            
            # Images section
            layout.addWidget(QLabel("Images:"))
            upload_btn = QPushButton("Upload Image")
            upload_btn.clicked.connect(lambda checked, s=stagename: self.upload_image(s))
            layout.addWidget(upload_btn)
            
            view_btn = QPushButton("View/Edit Images")
            view_btn.clicked.connect(lambda checked, s=stagename: self.view_images(s))
            layout.addWidget(view_btn)
            
            # Design Review
            review_cb = QCheckBox(f"Conducted {reviews[i]} Review")
            self.project_data["stages"][stagename]["review_cb"] = review_cb
            layout.addWidget(review_cb)
            
            # Complete Stage
            complete_btn = QPushButton("Complete Stage")
            complete_btn.clicked.connect(lambda checked, s=stage: self.complete_stage(s))
            layout.addWidget(complete_btn)
            
            tab.setLayout(layout)
            self.tab_widget.addTab(tab, stage)
        
        # Documentation tab
        self.create_documentation_tab()

    def create_documentation_tab(self):
        doc_tab = QWidget()
        layout = QVBoxLayout()
        
        # Project Image change
        layout.addWidget(QLabel("Project Image:"))
        change_img_btn = QPushButton("Add/Change Project Image")
        change_img_btn.clicked.connect(self.change_project_image)
        layout.addWidget(change_img_btn)
        
        # Stage checkboxes
        self.doc_include = {}
        for stage in ["Conceptual", "Preliminary", "Detail"]:
            cb = QCheckBox(f"Include {stage}")
            cb.setEnabled(self.completed_stages[stage])
            self.doc_include[stage] = cb
            layout.addWidget(cb)
        
        # Documentation options
        self.doc_options = {
            "include_images": QCheckBox("Include Images"),
            "include_date": QCheckBox("Include Date"),
            "include_page_numbers": QCheckBox("Include Page Numbers"),
            "compile_pdf": QCheckBox("Compile to PDF")
        }
        
        for cb in self.doc_options.values():
            cb.setChecked(True)
            layout.addWidget(cb)
        
        # Generate button
        generate_btn = QPushButton("Generate")
        generate_btn.clicked.connect(self.generate_report)
        layout.addWidget(generate_btn)
        
        layout.addStretch()
        doc_tab.setLayout(layout)
        self.tab_widget.addTab(doc_tab, "Documentation")

    def refresh_params(self, stagename):
        param_layout = self.project_data["stages"][stagename]["param_layout"]
        
        # Clear existing widgets
        while param_layout.count():
            child = param_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        self.project_data["stages"][stagename]["param_widgets"] = {}
        config = self.project_data["stages"][stagename]["parameters_config"]
        
        for param in config:
            name = param["name"]
            label_text = f"* {name} *:" if param["required"] else f"{name}:"
            param_layout.addWidget(QLabel(label_text))
            
            line_edit = QLineEdit()
            line_edit.setText(self.project_data["stages"][stagename]["parameters"].get(name, ""))
            param_layout.addWidget(line_edit)
            self.project_data["stages"][stagename]["param_widgets"][name] = line_edit

    def configure_parameters(self, stagename):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Configure Parameters for {stagename}")
        dialog.setGeometry(200, 200, 400, 300)
        
        layout = QVBoxLayout()
        
        listbox = QListWidget()
        config = self.project_data["stages"][stagename]["parameters_config"]
        for param in config:
            listbox.addItem(param["name"] + (" (required)" if param["required"] else ""))
        layout.addWidget(listbox)
        
        btn_layout = QHBoxLayout()
        
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(lambda: self.add_param(stagename, listbox, config))
        btn_layout.addWidget(add_btn)
        
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(lambda: self.edit_param(stagename, listbox, config))
        btn_layout.addWidget(edit_btn)
        
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda: self.remove_param(stagename, listbox, config))
        btn_layout.addWidget(remove_btn)
        
        done_btn = QPushButton("Done")
        done_btn.clicked.connect(lambda: [self.refresh_params(stagename), dialog.accept()])
        btn_layout.addWidget(done_btn)
        
        layout.addLayout(btn_layout)
        dialog.setLayout(layout)
        dialog.exec()

    def add_param(self, stagename, listbox, config):
        name, ok = QInputDialog.getText(self, "Add Parameter", "Parameter name:")
        if ok and name:
            # PyQt6: QMessageBox.Yes -> QMessageBox.StandardButton.Yes
            reply = QMessageBox.question(self, "Required", "Is this parameter required?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            required = (reply == QMessageBox.StandardButton.Yes)
            config.append({"name": name, "required": required})
            listbox.addItem(name + (" (required)" if required else ""))
            if name not in self.project_data["stages"][stagename]["parameters"]:
                self.project_data["stages"][stagename]["parameters"][name] = ""

    def edit_param(self, stagename, listbox, config):
        current_row = listbox.currentRow()
        if current_row >= 0:
            param = config[current_row]
            name, ok = QInputDialog.getText(self, "Edit Parameter", "Parameter name:", 
                                           text=param["name"])
            if ok and name:
                # PyQt6: QMessageBox.Yes -> QMessageBox.StandardButton.Yes
                reply = QMessageBox.question(self, "Required", "Is this parameter required?",
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                required = (reply == QMessageBox.StandardButton.Yes)
                old_name = param["name"]
                config[current_row] = {"name": name, "required": required}
                listbox.item(current_row).setText(name + (" (required)" if required else ""))
                if old_name != name:
                    if old_name in self.project_data["stages"][stagename]["parameters"]:
                        self.project_data["stages"][stagename]["parameters"][name] = \
                            self.project_data["stages"][stagename]["parameters"].pop(old_name)

    def remove_param(self, stagename, listbox, config):
        current_row = listbox.currentRow()
        if current_row >= 0:
            old_name = config[current_row]["name"]
            del config[current_row]
            listbox.takeItem(current_row)
            if old_name in self.project_data["stages"][stagename]["parameters"]:
                del self.project_data["stages"][stagename]["parameters"][old_name]

    def add_note_tab(self, stagename, name=None):
        if not name:
            name, ok = QInputDialog.getText(self, "Note Name", "Enter note name:")
            if not ok or not name:
                return
        
        notes_text = QTextEdit()
        notes_tabs = self.project_data["stages"][stagename]["notes_tabs"]
        notes_tabs.addTab(notes_text, name)
        self.project_data["stages"][stagename]["notes"][name] = {
            "widget": notes_text,
            "file": f"{self.project_data['name']}_{stagename}_{name}.md"
        }

    def upload_image(self, stagename):
        file, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Image Files (*.jpg *.png *.gif)")
        if file:
            caption, ok = QInputDialog.getText(self, "Caption", "Enter image caption:")
            self.project_data["stages"][stagename]["images"].append({
                "path": file,
                "caption": caption if ok else ""
            })

    def view_images(self, stagename):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{stagename} Images")
        dialog.setGeometry(200, 200, 600, 400)
        
        layout = QVBoxLayout()
        
        tree = QTreeWidget()
        tree.setHeaderLabels(["Caption"])
        
        for i, img in enumerate(self.project_data["stages"][stagename]["images"]):
            item = QTreeWidgetItem([img["caption"]])
            # PyQt6: Qt.UserRole -> Qt.ItemDataRole.UserRole
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            tree.addTopLevelItem(item)
        
        layout.addWidget(tree)
        
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setMinimumHeight(200)
        layout.addWidget(image_label)
        
        def show_image():
            current = tree.currentItem()
            if current:
                idx = current.data(0, Qt.ItemDataRole.UserRole)
                img_path = self.project_data["stages"][stagename]["images"][idx]["path"]
                if os.path.exists(img_path):
                    pixmap = QPixmap(img_path)
                    image_label.setPixmap(pixmap.scaled(400, 400, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        
        tree.itemSelectionChanged.connect(show_image)
        
        def edit_selected():
            current = tree.currentItem()
            if current:
                idx = current.data(0, Qt.ItemDataRole.UserRole)
                img = self.project_data["stages"][stagename]["images"][idx]
                caption, ok = QInputDialog.getText(self, "Edit Caption", "Caption:", text=img["caption"])
                if ok:
                    img["caption"] = caption
                    current.setText(0, caption)
        
        edit_btn = QPushButton("Edit Selected")
        edit_btn.clicked.connect(edit_selected)
        layout.addWidget(edit_btn)
        
        dialog.setLayout(layout)
        dialog.exec()

    def change_project_image(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Image Files (*.jpg *.png *.gif)")
        if file:
            basename = os.path.basename(file)
            dst = os.path.join(self.project_dir, basename)
            shutil.copy(file, dst)
            self.project_data["image"] = basename
            # Update display
            if self.proj_img_label:
                pixmap = QPixmap(dst)
                self.proj_img_label.setPixmap(pixmap.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def complete_stage(self, stage):
        stagename = stage.replace(" Design", "")
        
        config = self.project_data["stages"][stagename]["parameters_config"]
        params_filled = all(self.project_data["stages"][stagename]["param_widgets"][param["name"]].text().strip() 
                          for param in config if param["required"])
        
        if not params_filled:
            QMessageBox.warning(self, "Incomplete", "Fill all required parameters.")
            return
        
        if not self.project_data["stages"][stagename]["review_cb"].isChecked():
            QMessageBox.warning(self, "Incomplete", "Conduct the design review.")
            return
        
        self.completed_stages[stagename] = True
        QMessageBox.information(self, "Completed", f"{stage} completed!")
        
        if stagename == "Conceptual":
            self.tab_widget.setTabEnabled(1, True)
        elif stagename == "Preliminary":
            self.tab_widget.setTabEnabled(2, True)
        
        # Enable checkbox in Documentation
        self.doc_include[stagename].setEnabled(True)

    def export_parameter_config(self):
        config_data = {
            "version": "1.0",
            "stages": {}
        }
        
        for stagename in ["Conceptual", "Preliminary", "Detail"]:
            config_data["stages"][stagename] = self.project_data["stages"][stagename]["parameters_config"]
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Parameter Configuration", 
                                                   "parameter_config.json", 
                                                   "JSON Files (*.json);;All Files (*)")
        
        if file_path:
            try:
                with open(file_path, "w") as f:
                    json.dump(config_data, f, indent=2)
                QMessageBox.information(self, "Success", f"Parameter configuration exported to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export parameter configuration:\n{e}")

    def import_parameter_config(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Parameter Configuration", 
                                                   "", "JSON Files (*.json);;All Files (*)")
        
        if not file_path:
            return
        
        try:
            with open(file_path, "r") as f:
                config_data = json.load(f)
            
            if "stages" not in config_data:
                QMessageBox.critical(self, "Invalid File", "The selected file is not a valid parameter configuration file.")
                return
            
            # PyQt6: QMessageBox.Yes -> QMessageBox.StandardButton.Yes
            reply = QMessageBox.question(self, "Confirm Import",
                                        "This will replace the current parameter configuration for all stages.\n\n"
                                        "Any existing parameter values will be preserved if the parameter names match.\n\n"
                                        "Continue?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            for stagename in ["Conceptual", "Preliminary", "Detail"]:
                if stagename in config_data["stages"]:
                    old_params = self.project_data["stages"][stagename]["parameters"].copy()
                    self.project_data["stages"][stagename]["parameters_config"] = config_data["stages"][stagename]
                    
                    new_param_names = [p["name"] for p in config_data["stages"][stagename]]
                    preserved_params = {k: v for k, v in old_params.items() if k in new_param_names}
                    self.project_data["stages"][stagename]["parameters"] = preserved_params
                    
                    for param in config_data["stages"][stagename]:
                        if param["name"] not in self.project_data["stages"][stagename]["parameters"]:
                            self.project_data["stages"][stagename]["parameters"][param["name"]] = ""
                    
                    if "param_layout" in self.project_data["stages"][stagename]:
                        self.refresh_params(stagename)
            
            QMessageBox.information(self, "Success", "Parameter configuration imported successfully!")
            
        except json.JSONDecodeError:
            QMessageBox.critical(self, "Error", "The selected file is not a valid JSON file.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to import parameter configuration:\n{e}")

    def generate_report(self):
        selected_stages = [stage for stage in ["Conceptual", "Preliminary", "Detail"] 
                          if self.doc_include[stage].isChecked()]
        
        if not selected_stages:
            QMessageBox.warning(self, "No Stages", "Select at least one stage.")
            return
        
        if self.doc_options["compile_pdf"].isChecked() and shutil.which('pdflatex') is None:
            QMessageBox.critical(self, "LaTeX Not Found", 
                               "pdflatex is not installed or not in your PATH. Please install MiKTeX "
                               "(https://miktex.org/) or TeX Live, and ensure pdflatex is accessible from the command line.")
            return
        
        include_images = self.doc_options["include_images"].isChecked()
        include_date = self.doc_options["include_date"].isChecked()
        include_page_numbers = self.doc_options["include_page_numbers"].isChecked()
        
        date_str = datetime.date.today().strftime("%B %d, %Y") if include_date else ""
        
        # Handle unsaved images
        all_images = []
        for stage in selected_stages:
            for img in self.project_data["stages"][stage]["images"]:
                if os.path.isabs(img["path"]):
                    basename = os.path.basename(img["path"])
                    dst = os.path.join(self.project_dir, stage, basename)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy(img["path"], dst)
                    img["path"] = basename
                all_images.append((stage, img))
        
        # Handle project image
        if self.project_data["image"] and include_images:
            img_path = os.path.join(self.project_dir, self.project_data["image"])
            if not os.path.exists(img_path) and self.proj_img_path and os.path.exists(self.proj_img_path):
                shutil.copy(self.proj_img_path, img_path)
        
        # Generate LaTeX
        tex_content = r"""\documentclass{article}
\usepackage{graphicx}
\usepackage{amsmath}
\usepackage[margin=1in]{geometry}
"""
        if not include_page_numbers:
            tex_content += r"\pagestyle{empty}" + "\n"
        
        tex_content += r"\begin{document}" + "\n"
        tex_content += r"\begin{titlepage}" + "\n"
        tex_content += r"\vspace*{\fill}" + "\n"
        tex_content += r"\begin{center}" + "\n"
        tex_content += r"{\huge " + self.project_data["name"].replace("\n", "\\\\") + r" \par}" + "\n"
        tex_content += r"\vspace{1cm}" + "\n"
        tex_content += r"{\Large " + self.project_data["author"].replace("\n", "\\\\") + r" \par}" + "\n"
        if include_date:
            tex_content += r"\vspace{1cm}" + "\n"
            tex_content += r"{\large " + date_str + r" \par}" + "\n"
        tex_content += r"\end{center}" + "\n"
        tex_content += r"\vspace*{\fill}" + "\n"
        tex_content += r"\end{titlepage}" + "\n"
        
        tex_content += r"\section{Abstract}" + "\n"
        tex_content += self.project_data["summary"].replace("\n", "\\\\") + r"\\" + "\n"
        
        if self.project_data["image"] and include_images and os.path.exists(os.path.join(self.project_dir, self.project_data["image"])):
            tex_content += r"\begin{center}" + "\n"
            tex_content += r"\includegraphics[width=0.5\textwidth]{" + self.project_data["image"] + r"}" + "\n"
            tex_content += r"\end{center}" + "\n"
        
        for stage in selected_stages:
            tex_content += r"\section{" + stage + r" Design}" + "\n"
            tex_content += r"\subsection{Parameters}" + "\n"
            tex_content += r"\begin{itemize}" + "\n"
            for param in self.project_data["stages"][stage]["parameters_config"]:
                name = param["name"]
                value = self.project_data["stages"][stage]["param_widgets"][name].text().replace("\n", "\\\\")
                if not param["required"] and not value.strip():
                    continue
                tex_content += r"\item \textbf{" + name.replace("\n", "\\\\") + r":} " + value + "\n"
            tex_content += r"\end{itemize}" + "\n"
            
            tex_content += r"\subsection{Notes}" + "\n"
            for name, note in self.project_data["stages"][stage]["notes"].items():
                note_text = note["widget"].toPlainText().strip().replace("\n", "\\\\")
                tex_content += r"\subsubsection{" + name.replace("\n", "\\\\") + r"}" + "\n" + note_text + r"\\" + "\n"
        
        if include_images and all_images:
            tex_content += r"\section{Figures}" + "\n"
            for i, (stage, img) in enumerate(all_images, 1):
                caption = img["caption"].replace("\n", "\\\\")
                tex_content += r"\begin{figure}[h]" + "\n"
                tex_content += r"\centering" + "\n"
                tex_content += r"\includegraphics[width=0.5\textwidth]{" + stage + "/" + img["path"] + r"}" + "\n"
                tex_content += r"\caption{" + caption + r"}" + "\n"
                tex_content += r"\end{figure}" + "\n"
        
        tex_content += r"\end{document}"
        
        tex_path = os.path.join(self.project_dir, "report.tex")
        with open(tex_path, "w") as f:
            f.write(tex_content)
        
        if self.doc_options["compile_pdf"].isChecked():
            try:
                subprocess.call(['pdflatex', '-interaction=nonstopmode', tex_path], cwd=self.project_dir)
                QMessageBox.information(self, "Generated", "Report PDF generated at " + os.path.join(self.project_dir, "report.pdf"))
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to compile PDF: {e}")
        else:
            QMessageBox.information(self, "Generated", "LaTeX file generated at " + tex_path)

    def save_project(self):
        if not self.project_dir:
            QMessageBox.warning(self, "No Directory", "Project directory not set.")
            return
        
        # Store state
        for stagename in ["Conceptual", "Preliminary", "Detail"]:
            self.project_data["stages"][stagename]["completed"] = self.completed_stages[stagename]
            self.project_data["stages"][stagename]["review_state"] = self.project_data["stages"][stagename]["review_cb"].isChecked()
        
        # Copy project image if needed
        if self.project_data["image"] and self.proj_img_path and os.path.exists(self.proj_img_path):
            dst = os.path.join(self.project_dir, self.project_data["image"])
            # FIX: Check if source and destination are different before copying
            if os.path.abspath(self.proj_img_path) != os.path.abspath(dst):
                shutil.copy(self.proj_img_path, dst)
        
        for stagename in ["Conceptual", "Preliminary", "Detail"]:
            stage_dir = os.path.join(self.project_dir, stagename)
            os.makedirs(stage_dir, exist_ok=True)
            
            # Save notes to MD
            for name, note in self.project_data["stages"][stagename]["notes"].items():
                md_path = os.path.join(stage_dir, note["file"])
                with open(md_path, "w") as f:
                    f.write(note["widget"].toPlainText())
            
            # Copy images and update paths
            for img in self.project_data["stages"][stagename]["images"]:
                basename = os.path.basename(img["path"])
                dst = os.path.join(stage_dir, basename)
                
                # FIX: Check if file exists AND is not the same file before copying
                if os.path.exists(img["path"]):
                    if os.path.abspath(img["path"]) != os.path.abspath(dst):
                        shutil.copy(img["path"], dst)
                
                img["path"] = basename
            
            # Sync parameters
            for param in self.project_data["stages"][stagename]["parameters_config"]:
                name = param["name"]
                self.project_data["stages"][stagename]["parameters"][name] = \
                    self.project_data["stages"][stagename]["param_widgets"][name].text()
        
        # Save JSON (without UI widgets)
        save_data = {
            "name": self.project_data["name"],
            "author": self.project_data["author"],
            "summary": self.project_data["summary"],
            "image": self.project_data["image"],
            "stages": {}
        }
        
        for stagename in ["Conceptual", "Preliminary", "Detail"]:
            save_data["stages"][stagename] = {
                "parameters": self.project_data["stages"][stagename]["parameters"],
                "images": self.project_data["stages"][stagename]["images"],
                "notes": {k: {"file": v["file"]} for k, v in self.project_data["stages"][stagename]["notes"].items()},
                "completed": self.project_data["stages"][stagename]["completed"],
                "review_state": self.project_data["stages"][stagename]["review_state"],
                "parameters_config": self.project_data["stages"][stagename]["parameters_config"]
            }
        
        json_path = os.path.join(self.project_dir, f"{self.project_data['name']}.json")
        with open(json_path, "w") as f:
            json.dump(save_data, f, indent=2)
        
        QMessageBox.information(self, "Saved", "Project saved successfully.")

    def load_project(self):
        json_file, _ = QFileDialog.getOpenFileName(self, "Load Project", "", "JSON Files (*.json)")
        if not json_file:
            return
        
        self.project_dir = os.path.dirname(json_file)
        
        with open(json_file, "r") as f:
            loaded_data = json.load(f)
        
        self.project_data["name"] = loaded_data["name"]
        self.project_data["author"] = loaded_data["author"]
        self.project_data["summary"] = loaded_data["summary"]
        self.project_data["image"] = loaded_data["image"]
        
        for stagename in ["Conceptual", "Preliminary", "Detail"]:
            self.project_data["stages"][stagename]["parameters"] = loaded_data["stages"][stagename]["parameters"]
            self.project_data["stages"][stagename]["images"] = loaded_data["stages"][stagename]["images"]
            self.project_data["stages"][stagename]["notes"] = loaded_data["stages"][stagename]["notes"]
            self.project_data["stages"][stagename]["completed"] = loaded_data["stages"][stagename].get("completed", False)
            self.project_data["stages"][stagename]["review_state"] = loaded_data["stages"][stagename].get("review_state", False)
            self.project_data["stages"][stagename]["parameters_config"] = loaded_data["stages"][stagename]["parameters_config"]
            self.completed_stages[stagename] = self.project_data["stages"][stagename]["completed"]
        
        self.setup_main_ui(is_loaded=True)
        
        # Reload stages
        for stagename in ["Conceptual", "Preliminary", "Detail"]:
            # Parameters
            self.refresh_params(stagename)
            
            # Notes
            for name, note in self.project_data["stages"][stagename]["notes"].items():
                notes_text = QTextEdit()
                md_path = os.path.join(self.project_dir, stagename, note["file"])
                if os.path.exists(md_path):
                    with open(md_path, "r") as f:
                        notes_text.setPlainText(f.read())
                self.project_data["stages"][stagename]["notes_tabs"].addTab(notes_text, name)
                note["widget"] = notes_text
            
            # Images (convert to absolute paths)
            for img in self.project_data["stages"][stagename]["images"]:
                img["path"] = os.path.join(self.project_dir, stagename, img["path"])
            
            # Review state
            self.project_data["stages"][stagename]["review_cb"].setChecked(
                self.project_data["stages"][stagename]["review_state"])
            
            # Enable doc checkboxes if completed
            if self.completed_stages[stagename]:
                self.doc_include[stagename].setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = UAVDesignTool()
    window.show()
    # PyQt6: exec_() -> exec()
    sys.exit(app.exec())