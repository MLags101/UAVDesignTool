import json
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

STAGE_NAMES = ("Conceptual", "Preliminary", "Detail")
IMAGES_DIRNAME = "images"


def sanitize_filename(name: str) -> str:
    """Make an arbitrary user string safe to use as a file name."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned[:120] or "untitled"


def default_stage_configs() -> Dict[str, List[Dict[str, Any]]]:
    return {
        "Conceptual": [
            {"name": "Configuration Type", "required": True},
            {"name": "Wing Type", "required": True},
            {"name": "Tail Type", "required": True},
            {"name": "Fuselage Geometry", "required": True},
            {"name": "Engine Type", "required": True},
            {"name": "Landing Gear Type", "required": True},
        ],
        "Preliminary": [
            {"name": "Max Takeoff Weight (W_TO)", "required": True},
            {"name": "Wing Area (S)", "required": True},
            {"name": "Engine Thrust/Power (T/P)", "required": True},
            {"name": "Autopilot Preliminary Data", "required": True},
        ],
        "Detail": [
            {"name": "Wing Parameters", "required": True},
            {"name": "Tail Parameters", "required": True},
            {"name": "Fuselage Parameters", "required": True},
            {"name": "Landing Gear Parameters", "required": True},
            {"name": "Engine Parameters", "required": True},
            {"name": "Autopilot Parameters", "required": True},
            {"name": "Subsystems Parameters", "required": True},
        ],
    }


@dataclass
class UAVStage:
    parameters: Dict[str, str] = field(default_factory=dict)
    images: List[Dict[str, str]] = field(default_factory=list)
    notes: Dict[str, Dict[str, str]] = field(default_factory=dict)
    completed: bool = False
    review_state: bool = False
    parameters_config: List[Dict[str, Any]] = field(default_factory=list)

    def required_names(self) -> List[str]:
        return [p["name"] for p in self.parameters_config if p.get("required")]

    def completion_ratio(self) -> float:
        """Fraction of required parameters that currently hold a value."""
        required = self.required_names()
        if not required:
            return 1.0
        filled = sum(1 for n in required if str(self.parameters.get(n, "")).strip())
        return filled / len(required)


@dataclass
class UAVProject:
    name: str = ""
    author: str = ""
    summary: str = ""
    image: Optional[str] = None
    tools: List[Dict[str, Any]] = field(default_factory=list)
    stages: Dict[str, UAVStage] = field(default_factory=dict)

    def __post_init__(self):
        if not self.stages:
            self.stages = {
                name: UAVStage(parameters_config=config)
                for name, config in default_stage_configs().items()
            }


class ProjectModel:
    def __init__(self):
        self.project_dir: Optional[str] = None
        self.json_path: Optional[str] = None
        self.data = UAVProject()

    # ------------------------------------------------------------------ paths
    @property
    def images_dir(self) -> str:
        return os.path.join(self.project_dir or "", IMAGES_DIRNAME)

    def resolve_path(self, stored_path: str) -> str:
        """Turn a stored (project-relative) asset path into an absolute one."""
        if not stored_path:
            return ""
        if os.path.isabs(stored_path):
            return stored_path
        return os.path.join(self.project_dir or "", stored_path.replace("\\", "/"))

    def import_asset(self, source_path: str) -> str:
        """Copy a file into the project images folder.

        Returns the project-relative path that should be stored in the model.
        Existing names are never overwritten -- a numeric suffix is added.
        """
        os.makedirs(self.images_dir, exist_ok=True)
        base, ext = os.path.splitext(os.path.basename(source_path))
        base = sanitize_filename(base)
        dest_path = os.path.join(self.images_dir, f"{base}{ext}")

        counter = 1
        while (os.path.exists(dest_path)
               and os.path.abspath(source_path) != os.path.abspath(dest_path)):
            dest_path = os.path.join(self.images_dir, f"{base}_{counter}{ext}")
            counter += 1

        if os.path.abspath(source_path) != os.path.abspath(dest_path):
            shutil.copy2(source_path, dest_path)

        return f"{IMAGES_DIRNAME}/{os.path.basename(dest_path)}"

    def note_filename(self, stage_name: str, note_name: str) -> str:
        return sanitize_filename(f"{self.data.name}_{stage_name}_{note_name}") + ".md"

    # --------------------------------------------------------------- lifecycle
    def create_project(self, name: str, author: str, summary: str,
                       img_path: str, project_folder: str):
        self.data = UAVProject(name=name, author=author, summary=summary)

        self.project_dir = os.path.join(project_folder, sanitize_filename(name))
        os.makedirs(self.project_dir, exist_ok=True)
        for folder in (*STAGE_NAMES, "Tools", IMAGES_DIRNAME):
            os.makedirs(os.path.join(self.project_dir, folder), exist_ok=True)

        if img_path and os.path.exists(img_path):
            self.data.image = self.import_asset(img_path)

        self.json_path = os.path.join(self.project_dir, f"{sanitize_filename(name)}.json")
        self.save_project()

    def load_project(self, json_file: str):
        with open(json_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        # Start from a clean project so loading a second one cannot inherit
        # stages, tools or images from the first.
        self.data = UAVProject()
        self.project_dir = os.path.dirname(os.path.abspath(json_file))
        self.json_path = os.path.abspath(json_file)

        self.data.name = loaded.get("name", "")
        self.data.author = loaded.get("author", "")
        self.data.summary = loaded.get("summary", "")
        self.data.image = self._migrate_asset_path(loaded.get("image"))
        self.data.tools = loaded.get("tools", []) or []

        defaults = default_stage_configs()
        for stage_name in STAGE_NAMES:
            stage_data = (loaded.get("stages") or {}).get(stage_name)
            if not stage_data:
                continue

            # Older files may omit the config entirely; fall back to defaults.
            param_config = stage_data.get("parameters_config") or defaults[stage_name]

            images = []
            for img in stage_data.get("images", []) or []:
                path = self._migrate_asset_path(img.get("path", ""), stage_name)
                if path:
                    images.append({"path": path, "caption": img.get("caption", "")})

            self.data.stages[stage_name] = UAVStage(
                parameters=stage_data.get("parameters", {}) or {},
                images=images,
                notes=stage_data.get("notes", {}) or {},
                completed=stage_data.get("completed", False),
                review_state=stage_data.get("review_state", False),
                parameters_config=param_config,
            )

        self.load_note_contents()

    def _migrate_asset_path(self, stored: Optional[str], stage_name: str = "") -> Optional[str]:
        """Locate an asset saved by an older version of the app.

        Earlier releases stored bare file names and scattered images between the
        project root, the stage folder and ``images/``. Anything that resolves is
        rewritten to the canonical ``images/<file>`` form.
        """
        if not stored:
            return stored
        if os.path.isabs(stored) and os.path.exists(stored):
            return stored

        normalised = stored.replace("\\", "/")
        basename = os.path.basename(normalised)
        candidates = [normalised, f"{IMAGES_DIRNAME}/{basename}", basename]
        if stage_name:
            candidates.insert(1, f"{stage_name}/{basename}")

        for candidate in candidates:
            if os.path.exists(os.path.join(self.project_dir or "", candidate)):
                return candidate
        return f"{IMAGES_DIRNAME}/{basename}"

    def load_note_contents(self):
        """Read every note's markdown file into the in-memory model."""
        for stage_name, stage in self.data.stages.items():
            stage_dir = os.path.join(self.project_dir or "", stage_name)
            for note_name, note in stage.notes.items():
                note.setdefault("file", self.note_filename(stage_name, note_name))
                md_path = os.path.join(stage_dir, note["file"])
                if os.path.exists(md_path):
                    with open(md_path, "r", encoding="utf-8") as f:
                        note["content"] = f.read()
                else:
                    note.setdefault("content", "")

    def save_project(self):
        if not self.project_dir:
            raise ValueError("Project directory is not set.")

        os.makedirs(self.images_dir, exist_ok=True)

        for stage_name, stage in self.data.stages.items():
            stage_dir = os.path.join(self.project_dir, stage_name)
            os.makedirs(stage_dir, exist_ok=True)

            # Note text lives on disk as markdown; the controller syncs the
            # editors into the model before we get here.
            for note_name, note in stage.notes.items():
                note.setdefault("file", self.note_filename(stage_name, note_name))
                md_path = os.path.join(stage_dir, note["file"])
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(note.get("content", ""))

        save_data = {
            "version": 2,
            "name": self.data.name,
            "author": self.data.author,
            "summary": self.data.summary,
            "image": self.data.image,
            "tools": self.data.tools,
            "stages": {
                stage_name: {
                    "parameters": stage.parameters,
                    "images": stage.images,
                    # Note bodies live in their .md files, not in the JSON.
                    "notes": {k: {"file": v["file"]} for k, v in stage.notes.items()},
                    "completed": stage.completed,
                    "review_state": stage.review_state,
                    "parameters_config": stage.parameters_config,
                }
                for stage_name, stage in self.data.stages.items()
            },
        }

        if not self.json_path:
            self.json_path = os.path.join(
                self.project_dir, f"{sanitize_filename(self.data.name)}.json")

        # Write via a temp file so an interrupted save cannot truncate the
        # existing project file.
        tmp_path = self.json_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.json_path)

    def delete_note(self, stage_name: str, note_name: str):
        """Drop a note from the model and remove its markdown file."""
        stage = self.data.stages.get(stage_name)
        if not stage or note_name not in stage.notes:
            return
        note = stage.notes.pop(note_name)
        md_path = os.path.join(self.project_dir or "", stage_name, note.get("file", ""))
        if note.get("file") and os.path.exists(md_path):
            try:
                os.remove(md_path)
            except OSError:
                pass  # Leaving a stale file behind is better than failing the delete.

    def update_project_description(self, name: str, author: str, summary: str):
        self.data.name = name
        self.data.author = author
        self.data.summary = summary

    def overall_progress(self) -> float:
        stages = list(self.data.stages.values())
        if not stages:
            return 0.0
        return sum(s.completion_ratio() for s in stages) / len(stages)
