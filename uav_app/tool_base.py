"""Loading and execution of user-supplied design tools.

Two tool styles are supported:

1. Plain module (preferred) -- the script defines a module level
   ``TOOL_METADATA`` dict and a ``run(inputs)`` function.
2. Class based -- the script defines a subclass of :class:`UAVTool`.

Either way the app only ever needs ``get_metadata()`` and ``run(inputs)``,
so both styles are normalised into a single callable wrapper.

``run(inputs)`` may return a plain string, or a dict carrying charts and
structured results::

    {"text": "...",
     "figures": [{"title": "Drag Polar", "png": b"..."}],
     "outputs": {"Wing Area (S)": {"value": 0.31, "unit": "m^2"}},
     "warnings": ["Static margin is marginal"]}
"""

import importlib.util
import os
import sys
import uuid
from typing import Any, Callable, Dict, List, Tuple

INPUT_TYPES = ("text", "number", "choice", "file")


class ToolError(Exception):
    """Raised when a tool script cannot be loaded or is malformed."""


def library_path() -> str:
    """Absolute path to the directory holding the bundled ``uavlib`` package."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.dirname(here),                       # repo checkout
        getattr(sys, "_MEIPASS", ""),                # frozen bundle
        here,
    ]
    for base in candidates:
        if base and os.path.isdir(os.path.join(base, "uavlib")):
            return base
    return os.path.dirname(here)


def register_library() -> str:
    """Put the bundled ``uavlib`` on ``sys.path`` for the process lifetime.

    Tools import ``uavlib`` from this one canonical location. The copy placed in
    each project's ``Tools/`` folder exists so the scripts still run standalone;
    importing that copy instead would give two different ``uavlib`` modules in
    ``sys.modules`` once a second project is opened.
    """
    base = library_path()
    if base and base not in sys.path:
        sys.path.insert(0, base)
    return base


class UAVTool:
    """Optional base class for tools that need instance state.

    Most tools do not need this -- a module with ``TOOL_METADATA`` and
    ``run(inputs)`` is enough.
    """

    @classmethod
    def get_metadata(cls) -> Dict[str, Any]:
        raise NotImplementedError("Tool must implement get_metadata()")

    def run(self, inputs: Dict[str, str]) -> str:
        raise NotImplementedError("Tool must implement run(inputs)")


class _ModuleTool(UAVTool):
    """Adapts a plain ``TOOL_METADATA`` + ``run()`` module to the tool API."""

    def __init__(self, metadata: Dict[str, Any], run_func: Callable[[Dict[str, str]], Any]):
        self._metadata = metadata
        self._run_func = run_func

    def get_metadata(self) -> Dict[str, Any]:  # type: ignore[override]
        return self._metadata

    def run(self, inputs: Dict[str, str]):
        return self._run_func(inputs)


def normalise_result(result: Any) -> Dict[str, Any]:
    """Coerce whatever a tool returned into the dict the GUI consumes."""
    if result is None:
        return {"text": "", "figures": [], "outputs": {}, "warnings": []}
    if not isinstance(result, dict):
        return {"text": str(result), "figures": [], "outputs": {}, "warnings": []}

    figures = []
    for figure in result.get("figures") or []:
        if not isinstance(figure, dict) or not figure.get("png"):
            continue
        figures.append({"title": str(figure.get("title", "Figure")),
                        "png": figure["png"]})

    outputs = {}
    for name, spec in (result.get("outputs") or {}).items():
        if isinstance(spec, dict):
            outputs[str(name)] = {"value": spec.get("value", ""),
                                  "unit": str(spec.get("unit", ""))}
        else:
            outputs[str(name)] = {"value": spec, "unit": ""}

    return {
        "text": str(result.get("text", "")),
        "figures": figures,
        "outputs": outputs,
        "warnings": [str(w) for w in (result.get("warnings") or [])],
    }


def _validate_input(spec: Any, index: int, source: str) -> Dict[str, Any]:
    if not isinstance(spec, dict) or "key" not in spec:
        raise ToolError(f"Input #{index + 1} in {source} needs at least a 'key'.")

    kind = str(spec.get("type", "text")).lower()
    if kind not in INPUT_TYPES:
        raise ToolError(f"Input '{spec['key']}' in {source} has unknown type "
                        f"'{kind}'. Use one of: {', '.join(INPUT_TYPES)}.")

    choices = [str(c) for c in (spec.get("choices") or [])]
    if kind == "choice" and not choices:
        raise ToolError(f"Input '{spec['key']}' in {source} is a choice but "
                        "lists no 'choices'.")

    def _number_or_none(field):
        value = spec.get(field)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ToolError(f"Input '{spec['key']}' in {source} has a "
                            f"non-numeric '{field}'.")

    return {
        "key": str(spec["key"]),
        "label": str(spec.get("label", spec["key"])),
        "unit": str(spec.get("unit", "")),
        "default": str(spec.get("default", "")),
        "help": str(spec.get("help", "")),
        "type": kind,
        "choices": choices,
        "min": _number_or_none("min"),
        "max": _number_or_none("max"),
    }


def _validate_metadata(metadata: Any, source: str) -> Dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ToolError(f"TOOL_METADATA in {source} must be a dict.")
    if not metadata.get("name"):
        raise ToolError(f"TOOL_METADATA in {source} is missing a 'name'.")

    inputs: List[Dict[str, Any]] = metadata.get("inputs") or []
    if not isinstance(inputs, list):
        raise ToolError(f"TOOL_METADATA['inputs'] in {source} must be a list.")

    normalised = [_validate_input(spec, i, source) for i, spec in enumerate(inputs)]

    seen = set()
    for spec in normalised:
        if spec["key"] in seen:
            raise ToolError(f"Duplicate input key '{spec['key']}' in {source}.")
        seen.add(spec["key"])

    return {
        "name": str(metadata["name"]),
        "description": str(metadata.get("description", "")),
        "category": str(metadata.get("category", "")),
        "inputs": normalised,
    }


class ToolManager:
    """Imports tool scripts from disk and hands back a ready-to-run tool."""

    @staticmethod
    def _import_module(file_path: str):
        if not os.path.exists(file_path):
            raise ToolError(f"Tool file not found: {file_path}")

        register_library()

        # A unique module name keeps two tools with the same file name from
        # clobbering one another in sys.modules.
        module_name = f"uav_tool_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ToolError(f"Could not import tool: {file_path}")

        module = importlib.util.module_from_spec(spec)
        # Registering before exec lets the script use dataclasses/pickle and
        # import siblings that live next to it.
        sys.modules[module_name] = module

        # The tool's own directory stays on sys.path for the process lifetime:
        # removing it here would break any import performed lazily inside run().
        tool_dir = os.path.dirname(os.path.abspath(file_path))
        if tool_dir not in sys.path:
            sys.path.append(tool_dir)

        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(module_name, None)
            raise ToolError(f"Error while importing {os.path.basename(file_path)}: {exc}") from exc
        return module

    @staticmethod
    def load_tool_from_file(file_path: str) -> Tuple[UAVTool, Dict[str, Any]]:
        """Return a ready tool instance and its validated metadata."""
        module = ToolManager._import_module(file_path)
        source = os.path.basename(file_path)

        # Style 2: a UAVTool subclass defined in this module.
        for item_name in dir(module):
            item = getattr(module, item_name)
            if (isinstance(item, type) and issubclass(item, UAVTool)
                    and item is not UAVTool and item.__module__ == module.__name__):
                instance = item()
                return instance, _validate_metadata(instance.get_metadata(), source)

        # Style 1: plain module with TOOL_METADATA + run().
        metadata = getattr(module, "TOOL_METADATA", None)
        run_func = getattr(module, "run", None)
        if metadata is not None and callable(run_func):
            tool = _ModuleTool(_validate_metadata(metadata, source), run_func)
            return tool, tool.get_metadata()

        raise ToolError(
            f"{source} is not a valid tool. Define TOOL_METADATA and run(inputs), "
            "or subclass UAVTool."
        )

    @staticmethod
    def sync_library(project_dir: str) -> bool:
        """Copy the bundled ``uavlib`` into a project's ``Tools`` folder.

        Keeps the project self-contained: its tool scripts still run with plain
        Python after the folder is moved to another machine.
        """
        import shutil

        source = os.path.join(library_path(), "uavlib")
        if not os.path.isdir(source):
            return False

        destination = os.path.join(project_dir, "Tools", "uavlib")
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        if os.path.abspath(source) == os.path.abspath(destination):
            return False
        if os.path.isdir(destination):
            shutil.rmtree(destination, ignore_errors=True)
        shutil.copytree(source, destination,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        return True


try:
    from PyQt6.QtCore import QThread, pyqtSignal

    class ToolWorker(QThread):
        """Runs a tool off the GUI thread.

        The signal is deliberately *not* called ``finished`` -- QThread already
        defines that, and shadowing it breaks Qt's own thread bookkeeping.
        """

        result_ready = pyqtSignal(dict)
        failed = pyqtSignal(str)

        def __init__(self, tool_instance: UAVTool, inputs: Dict[str, str], parent=None):
            super().__init__(parent)
            self.tool_instance = tool_instance
            self.inputs = inputs

        def run(self):
            try:
                self.result_ready.emit(normalise_result(self.tool_instance.run(self.inputs)))
            except Exception as exc:
                self.failed.emit(f"Error executing tool: {exc}")

except ImportError:  # PyQt6 absent -- tools remain importable as plain modules.
    ToolWorker = None  # type: ignore[assignment]
