"""Consistent text formatting for tool output.

Every tool used to hand-roll its own header rules and column alignment. These
helpers keep the output readable and uniform, and keep the ASCII-only discipline
that makes the LaTeX export straightforward.
"""

from . import units


class Report:
    """Accumulates formatted output lines."""

    WIDTH = 46

    def __init__(self, title=None):
        self.lines = []
        self._warnings = []
        if title:
            self.title(title)

    # ------------------------------------------------------------- structure
    def title(self, text):
        self.lines.append(f"=== {text} ===")
        return self

    def section(self, text):
        if self.lines:
            self.lines.append("")
        self.lines.append(text)
        self.lines.append("-" * min(len(text), self.WIDTH))
        return self

    def rule(self):
        self.lines.append("-" * self.WIDTH)
        return self

    def blank(self):
        self.lines.append("")
        return self

    def text(self, message):
        self.lines.append(str(message))
        return self

    # ---------------------------------------------------------------- values
    def value(self, label, value, unit="", decimals=3, note=""):
        """A labelled value, right-aligned in a fixed column."""
        if isinstance(value, (int, float)):
            formatted = f"{value:,.{decimals}f}"
        else:
            formatted = str(value)
        text = f"{formatted} {unit}".rstrip()
        line = f"  {label + ':':<30}{text}"
        if note:
            line += f"   {note}"
        self.lines.append(line)
        return self

    def dual(self, label, value_si, si_unit, imperial_unit, decimals=2):
        """A value shown in SI with its imperial equivalent."""
        try:
            imperial = units.to(value_si, imperial_unit)
        except units.UnitError:
            return self.value(label, value_si, si_unit, decimals)
        text = f"{value_si:,.{decimals}f} {si_unit}  ({imperial:,.{decimals}f} {imperial_unit})"
        self.lines.append(f"  {label + ':':<30}{text}")
        return self

    def table(self, headers, rows, aligns=None):
        """A simple aligned table."""
        columns = len(headers)
        aligns = aligns or ["<"] + [">"] * (columns - 1)
        widths = [len(str(h)) for h in headers]
        for row in rows:
            for i, cell in enumerate(row[:columns]):
                widths[i] = max(widths[i], len(str(cell)))

        header = "  " + "  ".join(f"{str(h):{aligns[i]}{widths[i]}}"
                                  for i, h in enumerate(headers))
        self.lines.append(header)
        self.lines.append("  " + "  ".join("-" * w for w in widths))
        for row in rows:
            self.lines.append("  " + "  ".join(
                f"{str(c):{aligns[i]}{widths[i]}}" for i, c in enumerate(row[:columns])))
        return self

    def bullet(self, text):
        self.lines.append(f"  - {text}")
        return self

    # -------------------------------------------------------------- warnings
    def warn(self, message):
        """A warning shown inline and collected for the structured result."""
        self.lines.append(f"  [!] {message}")
        self._warnings.append(str(message))
        return self

    def note(self, message):
        if message:
            self.lines.append(f"  Note: {message}")
        return self

    @property
    def warnings(self):
        return list(self._warnings)

    def __str__(self):
        return "\n".join(self.lines)

    def render(self):
        return str(self)


def result(report, outputs=None, figures=None):
    """Package a report into the structured dict the application understands.

    ``outputs`` maps a parameter name to a value; the app offers to write these
    back into the project's stage parameters.
    """
    payload = {"text": str(report)}
    if isinstance(report, Report) and report.warnings:
        payload["warnings"] = report.warnings
    if outputs:
        payload["outputs"] = {
            name: (spec if isinstance(spec, dict) else {"value": spec})
            for name, spec in outputs.items()
        }
    if figures:
        payload["figures"] = figures
    return payload


def error(message):
    """A uniform error string for tools to return on bad input."""
    return f"Error: {message}"
