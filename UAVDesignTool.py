"""Entry point for the UAV Design Organizer desktop application."""

import os
import sys



def _icon_path() -> str:
    """plane.ico sits beside this script, or in _MEIPASS once frozen."""
    for base in (getattr(sys, "_MEIPASS", ""), os.path.dirname(os.path.abspath(__file__))):
        candidate = os.path.join(base, "plane.ico")
        if base and os.path.exists(candidate):
            return candidate
    return ""


def main():
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication
    from uav_app.controllers import ProjectController
    from uav_app.models import ProjectModel
    from uav_app.theme import APP_NAME, ORG_NAME, apply_theme, load_theme_name
    from uav_app.views import MainWindow
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
    import multiprocessing
    multiprocessing.freeze_support()
    if "--optimization-worker" in sys.argv:
        folder = sys.argv[sys.argv.index("--optimization-worker") + 1]
        try:
            from uavlib.optimization.worker import execute
            code = execute(folder)
        except Exception as exc:
            import json
            import traceback
            with open(os.path.join(folder, "result.json"), "w", encoding="utf-8") as stream:
                json.dump({"ok": False, "error": str(exc), "traceback": traceback.format_exc()}, stream)
            code = 1
        sys.exit(code)
    main()
