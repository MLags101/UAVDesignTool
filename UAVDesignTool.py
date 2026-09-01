"""Entry point for the UAV Design Organizer desktop application."""

import os
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from uav_app.controllers import ProjectController
from uav_app.models import ProjectModel
from uav_app.theme import APP_NAME, ORG_NAME, apply_theme, load_theme_name
from uav_app.views import MainWindow


def _icon_path() -> str:
    """plane.ico sits beside this script, or in _MEIPASS once frozen."""
    for base in (getattr(sys, "_MEIPASS", ""), os.path.dirname(os.path.abspath(__file__))):
        candidate = os.path.join(base, "plane.ico")
        if base and os.path.exists(candidate):
            return candidate
    return ""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)

    icon = _icon_path()
    if icon:
        app.setWindowIcon(QIcon(icon))

    apply_theme(app, load_theme_name())

    model = ProjectModel()
    view = MainWindow()
    controller = ProjectController(view, model)
    view._controller = controller  # keep the controller alive for the app's lifetime

    view.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
