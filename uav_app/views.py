from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (QCheckBox, QDockWidget, QFrame, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QMainWindow, QPushButton,
                             QScrollArea, QSizePolicy, QSplitter, QStackedWidget,
                             QStatusBar, QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from .models import STAGE_NAMES

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"


def set_role(widget, role: str):
    """Tag a widget so the stylesheet can style it semantically."""
    widget.setProperty("role", role)
    return widget


def accent(button: QPushButton) -> QPushButton:
    button.setProperty("accent", True)
    return button


class ImageDropListWidget(QListWidget):
    """Image list that also accepts files dropped from the OS."""

    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(False)

    @staticmethod
    def _image_urls(mime):
        return [url.toLocalFile() for url in mime.urls()
                if url.isLocalFile() and url.toLocalFile().lower().endswith(IMAGE_EXTENSIONS)]

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self._image_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() and self._image_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        files = self._image_urls(event.mimeData()) if event.mimeData().hasUrls() else []
        if files:
            self.files_dropped.emit(files)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class MainWindow(QMainWindow):
    close_requested = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("UAV Design Organizer")
        self.setGeometry(100, 100, 1360, 860)
        self.setMinimumSize(980, 640)

        self.project_ui_ready = False
        self.stage_views = {}

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.init_start_page()

    def closeEvent(self, event):
        self.close_requested.emit(event)
        if event.isAccepted():
            super().closeEvent(event)

    # ------------------------------------------------------------ start page
    def init_start_page(self):
        self.clear_layout(self.main_layout)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(60, 40, 60, 40)
        layout.addStretch()

        title = set_role(QLabel("UAV Design Organizer"), "title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = set_role(
            QLabel("Stage-gated design record keeping for fixed wing and multirotor aircraft."),
            "subtle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(28)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.new_btn = accent(QPushButton("New Project"))
        self.new_btn.setMinimumWidth(170)
        self.load_btn = QPushButton("Open Project…")
        self.load_btn.setMinimumWidth(170)
        btn_layout.addWidget(self.new_btn)
        btn_layout.addWidget(self.load_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addSpacing(30)

        recent_box = QGroupBox("Recent Projects")
        recent_box.setMaximumWidth(640)
        recent_layout = QVBoxLayout(recent_box)
        self.recent_list = QListWidget()
        self.recent_list.setMaximumHeight(190)
        recent_layout.addWidget(self.recent_list)
        self.recent_empty_label = set_role(
            QLabel("No recent projects yet — create or open one to get started."), "subtle")
        recent_layout.addWidget(self.recent_empty_label)

        recent_row = QHBoxLayout()
        recent_row.addStretch()
        recent_row.addWidget(recent_box)
        recent_row.addStretch()
        layout.addLayout(recent_row)

        layout.addStretch()
        self.main_layout.addWidget(container)

    def show_recent_projects(self, entries):
        """entries: list of (display_name, json_path)."""
        self.recent_list.clear()
        for name, path in entries:
            item_text = f"{name}"
            self.recent_list.addItem(item_text)
            item = self.recent_list.item(self.recent_list.count() - 1)
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
        has_entries = bool(entries)
        self.recent_list.setVisible(has_entries)
        self.recent_empty_label.setVisible(not has_entries)

    # ----------------------------------------------------------- project page
    def init_project_ui(self):
        self.clear_layout(self.main_layout)
        self.main_layout.setContentsMargins(10, 10, 10, 6)

        self._build_menus()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.progress_label = set_role(QLabel(""), "subtle")
        self.status_bar.addPermanentWidget(self.progress_label)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_layout.addWidget(main_splitter)

        main_splitter.addWidget(self._build_sidebar())

        self.central_stack = QStackedWidget()
        main_splitter.addWidget(self.central_stack)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([230, 1000])

        self.stage_views = {}
        for stage in STAGE_NAMES:
            sv = self.create_stage_tab(stage)
            self.stage_views[stage] = sv
            self.central_stack.addWidget(sv["widget"])

        self.doc_view = self.create_documentation_tab()
        self.central_stack.addWidget(self.doc_view["widget"])

        self.sidebar_list.currentRowChanged.connect(self._on_sidebar_changed)
        self.sidebar_list.setCurrentRow(0)

        self.tools_dock = QDockWidget("Tools", self)
        self.tools_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                                        | Qt.DockWidgetArea.RightDockWidgetArea)
        self.tool_view = self.create_tools_view()
        self.tools_dock.setWidget(self.tool_view["widget"])
        self.tools_dock.setMinimumWidth(360)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.tools_dock)
        self.view_menu.addAction(self.tools_dock.toggleViewAction())

        self.project_ui_ready = True

    def _on_sidebar_changed(self, row):
        if 0 <= row < self.central_stack.count():
            self.central_stack.setCurrentIndex(row)

    def _build_menus(self):
        # Rebuilt from scratch so re-entering a project cannot duplicate menus.
        self.menuBar().clear()
        menubar = self.menuBar()

        self.file_menu = menubar.addMenu("&File")
        self.save_action = self._action(self.file_menu, "Save Project", "Ctrl+S")
        self.file_menu.addSeparator()
        self.export_action = self._action(self.file_menu, "Export Parameter Configuration…")
        self.import_action = self._action(self.file_menu, "Import Parameter Configuration…")
        self.file_menu.addSeparator()
        self.import_tool_action = self._action(self.file_menu, "Import Tool Script…", "Ctrl+T")
        self.file_menu.addSeparator()
        self.generate_action = self._action(self.file_menu, "Export to Overleaf (ZIP)…", "Ctrl+E")
        self.file_menu.addSeparator()
        self.quit_action = self._action(self.file_menu, "Quit", "Ctrl+Q")

        self.view_menu = menubar.addMenu("&View")
        self.command_palette_action = self._action(
            self.view_menu, "Command Palette", "Ctrl+Shift+P")
        self.view_menu.addSeparator()
        self.theme_action = self._action(self.view_menu, "Toggle Light/Dark Theme", "Ctrl+Shift+T")
        self.view_menu.addSeparator()

        self.help_menu = menubar.addMenu("&Help")
        self.shortcuts_action = self._action(self.help_menu, "Keyboard Shortcuts", "F1")
        self.about_action = self._action(self.help_menu, "About")

    def _action(self, menu, text, shortcut=None) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        menu.addAction(action)
        return action

    def _build_sidebar(self) -> QWidget:
        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 6, 0)

        self.project_name_label = set_role(QLabel(""), "heading")
        self.project_name_label.setWordWrap(True)
        sidebar_layout.addWidget(self.project_name_label)
        self.project_author_label = set_role(QLabel(""), "subtle")
        self.project_author_label.setWordWrap(True)
        sidebar_layout.addWidget(self.project_author_label)
        sidebar_layout.addSpacing(8)

        self.sidebar_list = QListWidget()
        self.sidebar_list.setObjectName("sidebar")
        self.sidebar_list.setMinimumWidth(190)
        self.sidebar_list.setMaximumWidth(280)
        for item in (*STAGE_NAMES, "Documentation"):
            self.sidebar_list.addItem(item)
        sidebar_layout.addWidget(self.sidebar_list)

        self.proj_img_label = QLabel()
        self.proj_img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.proj_img_label.setMinimumHeight(10)
        sidebar_layout.addWidget(self.proj_img_label)
        sidebar_layout.addStretch()
        return sidebar_widget

    def set_stage_status(self, stage_name, completed: bool, ratio: float):
        """Reflect stage progress in the sidebar label."""
        row = list(STAGE_NAMES).index(stage_name)
        item = self.sidebar_list.item(row)
        if item is None:
            return
        if completed:
            badge = "  ✓"
        elif ratio >= 1.0:
            badge = "  ●"
        elif ratio > 0:
            badge = f"  {int(ratio * 100)}%"
        else:
            badge = ""
        item.setText(f"{stage_name}{badge}")
        item.setToolTip("Stage complete" if completed
                        else f"{int(ratio * 100)}% of required parameters filled")

    # ------------------------------------------------------------ stage pages
    def create_stage_tab(self, stage_name):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 0, 0, 0)

        header_layout = QHBoxLayout()
        header_layout.addWidget(set_role(QLabel(f"{stage_name} Design"), "heading"))
        header_layout.addStretch()
        status_label = set_role(QLabel(""), "subtle")
        header_layout.addWidget(status_label)
        detach_btn = QPushButton("Detach")
        detach_btn.setToolTip("Open this stage in its own window")
        header_layout.addWidget(detach_btn)
        layout.addLayout(header_layout)

        v_splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(v_splitter)

        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        param_group = QGroupBox("Parameters")
        param_group_layout = QVBoxLayout(param_group)

        param_filter = QLineEdit()
        param_filter.setPlaceholderText("Filter parameters…")
        param_filter.setClearButtonEnabled(True)
        param_group_layout.addWidget(param_filter)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        param_content = QWidget()
        param_layout = QVBoxLayout(param_content)
        param_layout.setContentsMargins(2, 2, 8, 2)
        scroll.setWidget(param_content)
        param_group_layout.addWidget(scroll)

        configure_btn = QPushButton("Configure Parameters…")
        param_group_layout.addWidget(configure_btn)
        top_layout.addWidget(param_group, 2)

        img_group = QGroupBox("Images")
        img_layout = QVBoxLayout(img_group)
        img_list = ImageDropListWidget()
        img_list.setToolTip("Drag image files here to attach them to this stage")
        img_layout.addWidget(img_list)
        img_layout.addWidget(set_role(QLabel("Drag & drop images anywhere in this list"), "subtle"))

        img_btn_layout = QHBoxLayout()
        upload_btn = QPushButton("Add…")
        view_btn = QPushButton("View / Edit…")
        img_btn_layout.addWidget(upload_btn)
        img_btn_layout.addWidget(view_btn)
        img_layout.addLayout(img_btn_layout)
        top_layout.addWidget(img_group, 1)

        v_splitter.addWidget(top_widget)

        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout(notes_group)
        notes_tabs = QTabWidget()
        notes_tabs.setMovable(True)
        notes_layout.addWidget(notes_tabs)

        notes_btn_layout = QHBoxLayout()
        add_note_btn = QPushButton("Add Note")
        rename_note_btn = QPushButton("Rename Note")
        delete_note_btn = QPushButton("Delete Note")
        delete_note_btn.setProperty("danger", True)
        notes_btn_layout.addWidget(add_note_btn)
        notes_btn_layout.addWidget(rename_note_btn)
        notes_btn_layout.addWidget(delete_note_btn)
        notes_btn_layout.addStretch()
        word_count_label = set_role(QLabel(""), "subtle")
        notes_btn_layout.addWidget(word_count_label)
        notes_layout.addLayout(notes_btn_layout)

        v_splitter.addWidget(notes_group)
        v_splitter.setStretchFactor(0, 1)
        v_splitter.setStretchFactor(1, 2)

        footer_layout = QHBoxLayout()
        review_cb = QCheckBox(f"Conducted {stage_name} design review")
        complete_btn = accent(QPushButton("Complete Stage"))
        footer_layout.addWidget(review_cb)
        footer_layout.addStretch()
        footer_layout.addWidget(complete_btn)
        layout.addLayout(footer_layout)

        return {
            "widget": widget,
            "param_layout": param_layout,
            "param_filter": param_filter,
            "configure_btn": configure_btn,
            "status_label": status_label,
            "notes_tabs": notes_tabs,
            "add_note_btn": add_note_btn,
            "rename_note_btn": rename_note_btn,
            "delete_note_btn": delete_note_btn,
            "word_count_label": word_count_label,
            "img_list": img_list,
            "upload_btn": upload_btn,
            "view_btn": view_btn,
            "detach_btn": detach_btn,
            "review_cb": review_cb,
            "complete_btn": complete_btn,
            "param_widgets": {},   # {param name: QLineEdit}
            "param_rows": {},      # {param name: container QWidget} -- for filtering
            "note_editors": {},    # {note name: QTextEdit}
        }

    # ---------------------------------------------------------- documentation
    def create_documentation_tab(self):
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(6, 0, 0, 0)
        outer.addWidget(set_role(QLabel("Documentation"), "heading"))

        columns = QHBoxLayout()
        outer.addLayout(columns, 1)

        left = QVBoxLayout()
        columns.addLayout(left, 1)

        details_group = QGroupBox("Project Details")
        details_layout = QVBoxLayout(details_group)
        self.doc_summary_label = set_role(QLabel(""), "subtle")
        self.doc_summary_label.setWordWrap(True)
        details_layout.addWidget(self.doc_summary_label)
        edit_desc_btn = QPushButton("Edit Project Description…")
        details_layout.addWidget(edit_desc_btn)
        change_img_btn = QPushButton("Add / Change Project Image…")
        details_layout.addWidget(change_img_btn)
        left.addWidget(details_group)

        stages_group = QGroupBox("Include Stages")
        stages_layout = QVBoxLayout(stages_group)
        doc_include = {}
        for stage in STAGE_NAMES:
            cb = QCheckBox(stage)
            cb.setEnabled(False)
            cb.setToolTip("Complete this stage to include it in the report")
            doc_include[stage] = cb
            stages_layout.addWidget(cb)
        left.addWidget(stages_group)

        options_group = QGroupBox("Report Options")
        options_layout = QVBoxLayout(options_group)
        doc_options = {
            "include_images": QCheckBox("Include images"),
            "include_date": QCheckBox("Include date"),
            "include_page_numbers": QCheckBox("Include page numbers and table of contents"),
        }
        for cb in doc_options.values():
            cb.setChecked(True)
            options_layout.addWidget(cb)
        left.addWidget(options_group)

        generate_btn = accent(QPushButton("Export to Overleaf (ZIP)"))
        generate_btn.setMinimumHeight(40)
        left.addWidget(generate_btn)
        left.addStretch()

        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)
        doc_proj_img_label = QLabel()
        doc_proj_img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        doc_proj_img_label.setMinimumHeight(240)
        set_role(doc_proj_img_label, "dropzone")
        doc_proj_img_label.setText("No project image set")
        preview_layout.addWidget(doc_proj_img_label)

        doc_summary_stats = set_role(QLabel(""), "subtle")
        doc_summary_stats.setWordWrap(True)
        doc_summary_stats.setAlignment(Qt.AlignmentFlag.AlignTop)
        doc_summary_stats.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(doc_summary_stats)
        columns.addWidget(preview_group, 1)

        return {
            "widget": widget,
            "change_img_btn": change_img_btn,
            "edit_desc_btn": edit_desc_btn,
            "doc_include": doc_include,
            "doc_options": doc_options,
            "generate_btn": generate_btn,
            "doc_proj_img_label": doc_proj_img_label,
            "doc_summary_label": self.doc_summary_label,
            "doc_summary_stats": doc_summary_stats,
        }

    # ------------------------------------------------------------------ tools
    def create_tools_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(set_role(QLabel("Available Tools"), "heading"))

        tool_filter = QLineEdit()
        tool_filter.setPlaceholderText("Search tools…")
        tool_filter.setClearButtonEnabled(True)
        layout.addWidget(tool_filter)

        tools_list = QListWidget()
        tools_list.setMaximumHeight(170)
        layout.addWidget(tools_list)

        btn_row = QHBoxLayout()
        import_tool_btn = QPushButton("Import…")
        remove_tool_btn = QPushButton("Remove")
        remove_tool_btn.setProperty("danger", True)
        btn_row.addWidget(import_tool_btn)
        btn_row.addWidget(remove_tool_btn)
        layout.addLayout(btn_row)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        tool_area = QScrollArea()
        tool_area.setWidgetResizable(True)
        tool_content = QWidget()
        tool_layout = QVBoxLayout(tool_content)
        tool_area.setWidget(tool_content)

        placeholder = set_role(QLabel(
            "Select a tool above, or import one with File ▸ Import Tool Script."), "subtle")
        placeholder.setWordWrap(True)
        tool_layout.addWidget(placeholder)
        tool_layout.addStretch()
        layout.addWidget(tool_area, 1)

        return {
            "widget": widget,
            "tools_list": tools_list,
            "tool_filter": tool_filter,
            "import_tool_btn": import_tool_btn,
            "remove_tool_btn": remove_tool_btn,
            "tool_layout": tool_layout,
        }

    # ----------------------------------------------------------------- helper
    @staticmethod
    def clear_layout(layout):
        """Remove and delete every item in a layout, recursively."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                MainWindow.clear_layout(item.layout())
                item.layout().deleteLater()
