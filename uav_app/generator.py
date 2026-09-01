import datetime
import os
import zipfile

import jinja2

# Order matters: the backslash must be replaced first, and its replacement
# must not be re-processed by the later brace rules.
_TEX_ESCAPES = [
    ("\\", r"\textbackslash"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
]


# Characters the design tools routinely emit that pdflatex cannot typeset
# directly. Substituted after escaping so the replacements survive intact.
_UNICODE_TEX = {
    "²": r"\textsuperscript{2}",
    "³": r"\textsuperscript{3}",
    "°": r"\textdegree{}",
    "±": r"$\pm$",
    "×": r"$\times$",
    "−": "-",
    "–": "--",
    "—": "---",
    "µ": r"$\mu$",
    "α": r"$\alpha$", "β": r"$\beta$", "γ": r"$\gamma$", "δ": r"$\delta$",
    "θ": r"$\theta$", "λ": r"$\lambda$", "μ": r"$\mu$", "π": r"$\pi$",
    "ρ": r"$\rho$", "σ": r"$\sigma$", "φ": r"$\phi$", "ω": r"$\omega$",
    "Δ": r"$\Delta$", "Ω": r"$\Omega$",
}


def escape_tex(text) -> str:
    """Escape a string so it renders literally in LaTeX."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    for char, replacement in _TEX_ESCAPES:
        text = text.replace(char, replacement)
    # \textbackslash needs its braces added after the brace rules have run,
    # otherwise they would be escaped too.
    text = text.replace(r"\textbackslash", r"\textbackslash{}")
    for char, replacement in _UNICODE_TEX.items():
        if char in text:
            text = text.replace(char, replacement)
    return text


def escape_tex_block(text) -> str:
    """Escape multi-line text, mapping blank lines to paragraph breaks."""
    escaped = escape_tex(text)
    paragraphs = [p.strip() for p in escaped.split("\n\n")]
    paragraphs = [p.replace("\n", r"\\" + "\n") for p in paragraphs if p]
    return "\n\n".join(paragraphs)


def _template_dir() -> str:
    """Templates sit next to this file, or in _MEIPASS when frozen."""
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    if os.path.isdir(local):
        return local
    import sys
    bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "templates")
    if os.path.isdir(bundled):
        return bundled
    return local


def generate_overleaf_zip(model, selected_stages, options, export_path=None) -> str:
    """Build a zip with main.tex plus every referenced image, ready for Overleaf.

    Returns the absolute path of the zip that was written.
    """
    project_dir = model.project_dir
    if not project_dir:
        raise ValueError("Project directory is not set.")

    if export_path is None:
        safe_name = (model.data.name or "UAV_Project").replace(" ", "_")
        export_path = os.path.join(project_dir, f"{safe_name}_Overleaf.zip")

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(_template_dir()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report.tex.j2")

    data = {
        "project": {
            "name": escape_tex(model.data.name),
            "author": escape_tex(model.data.author),
            "summary": escape_tex_block(model.data.summary),
            "image": None,
        },
        "date_str": (escape_tex(datetime.datetime.now().strftime("%B %d, %Y"))
                     if options.get("include_date") else ""),
        "include_page_numbers": options.get("include_page_numbers", True),
        "stages": [],
        "all_images": [],
    }

    include_images = options.get("include_images", True)
    images_to_bundle = []  # (absolute source, path inside the zip)

    def add_image(stored_path: str) -> str:
        abs_path = model.resolve_path(stored_path)
        if not abs_path or not os.path.exists(abs_path):
            return ""
        zip_path = f"images/{os.path.basename(abs_path)}"
        images_to_bundle.append((abs_path, zip_path))
        return zip_path

    if model.data.image and include_images:
        data["project"]["image"] = add_image(model.data.image) or None

    for stage_name in selected_stages:
        stage = model.data.stages[stage_name]
        data["stages"].append({
            "name": escape_tex(stage_name),
            "parameters": [
                {"name": escape_tex(k), "value": escape_tex(v)}
                for k, v in stage.parameters.items() if str(v).strip()
            ],
            "notes": [
                {"name": escape_tex(k), "content": escape_tex_block(v.get("content", ""))}
                for k, v in stage.notes.items() if v.get("content", "").strip()
            ],
        })

        if include_images:
            for img in stage.images:
                zip_path = add_image(img.get("path", ""))
                if zip_path:
                    data["all_images"].append({
                        "path": zip_path,
                        "caption": escape_tex(img.get("caption", "")).replace("\n", " "),
                    })

    tex_content = template.render(**data)

    with zipfile.ZipFile(export_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        zipf.writestr("main.tex", tex_content)
        added = set()
        for abs_src, rel_dest in images_to_bundle:
            if rel_dest not in added:
                zipf.write(abs_src, rel_dest)
                added.add(rel_dest)

    return export_path
