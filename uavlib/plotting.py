"""Chart helpers for tools that return figures.

Tools call :func:`figure` and get back PNG bytes, which the application renders
inline and can attach to a project stage. matplotlib is imported lazily and
forced onto the Agg backend so nothing tries to open a window from the worker
thread.
"""

import io

_AVAILABLE = None

# Colours chosen to stay legible on both the light and dark application themes.
PALETTE = ["#4a90e2", "#e2725b", "#41b957", "#d9a323", "#9b59b6",
           "#1abc9c", "#e74c3c", "#34495e"]


def available() -> bool:
    """Whether matplotlib can be imported."""
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            import matplotlib
            matplotlib.use("Agg", force=True)
            import matplotlib.pyplot  # noqa: F401
            _AVAILABLE = True
        except Exception:
            _AVAILABLE = False
    return _AVAILABLE


def _pyplot():
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    return plt


def new_axes(width=7.0, height=4.5, dpi=140):
    """Create a themed figure and axes."""
    plt = _pyplot()
    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    ax.grid(True, alpha=0.25, linewidth=0.7)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    return fig, ax


def to_png(fig, close=True) -> bytes:
    """Render a figure to PNG bytes."""
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight", facecolor="white")
    if close:
        _pyplot().close(fig)
    return buffer.getvalue()


def figure(title: str, png_bytes: bytes) -> dict:
    """Wrap PNG bytes in the structure the application expects."""
    return {"title": title, "png": png_bytes}


def line_chart(title, x_label, y_label, series, markers=None,
               width=7.0, height=4.5) -> dict:
    """A line chart from ``series`` = [(label, xs, ys), ...].

    ``markers`` = [(label, x, y), ...] annotates specific points, which is how
    design points and optima are called out.
    """
    if not available():
        raise RuntimeError("matplotlib is not installed.")
    fig, ax = new_axes(width, height)

    for index, (label, xs, ys) in enumerate(series):
        ax.plot(xs, ys, label=label, color=PALETTE[index % len(PALETTE)],
                linewidth=2.0)

    for index, (label, x, y) in enumerate(markers or []):
        ax.plot([x], [y], "o", color=PALETTE[(index + 2) % len(PALETTE)],
                markersize=8, markeredgecolor="white", markeredgewidth=1.4,
                zorder=5)
        ax.annotate(label, (x, y), textcoords="offset points", xytext=(8, 8),
                    fontsize=9)

    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title, fontsize=12, fontweight="bold")
    if len(series) > 1 or markers:
        ax.legend(frameon=False, fontsize=9)
    return figure(title, to_png(fig))


def filled_region_chart(title, x_label, y_label, constraints, design_point=None,
                        feasible="above", width=7.0, height=5.0) -> dict:
    """Constraint diagram: several boundary curves plus the feasible region.

    ``constraints`` = [(label, xs, ys), ...]. ``feasible`` says whether the
    acceptable region lies above or below the binding envelope.
    """
    if not available():
        raise RuntimeError("matplotlib is not installed.")
    fig, ax = new_axes(width, height)

    for index, (label, xs, ys) in enumerate(constraints):
        ax.plot(xs, ys, label=label, color=PALETTE[index % len(PALETTE)],
                linewidth=2.0)

    # The binding envelope is the worst constraint at each station.
    if constraints:
        xs = constraints[0][1]
        combiner = max if feasible == "above" else min
        envelope = [combiner(c[2][i] for c in constraints) for i in range(len(xs))]
        top = ax.get_ylim()[1]
        if feasible == "above":
            ax.fill_between(xs, envelope, top, alpha=0.12, color="#41b957",
                            label="Feasible")
        else:
            ax.fill_between(xs, 0, envelope, alpha=0.12, color="#41b957",
                            label="Feasible")
        ax.plot(xs, envelope, color="#2c3e50", linewidth=1.2, linestyle="--")

    if design_point:
        label, x, y = design_point
        ax.plot([x], [y], "*", color="#e2725b", markersize=17,
                markeredgecolor="white", markeredgewidth=1.2, zorder=6)
        ax.annotate(label, (x, y), textcoords="offset points", xytext=(10, 10),
                    fontsize=9, fontweight="bold")

    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.legend(frameon=False, fontsize=9, loc="best")
    return figure(title, to_png(fig))


def bar_chart(title, x_label, y_label, labels, values,
              width=7.0, height=4.5) -> dict:
    """Horizontal bar chart, used for drag and mass breakdowns."""
    if not available():
        raise RuntimeError("matplotlib is not installed.")
    fig, ax = new_axes(width, height)
    positions = range(len(labels))
    ax.barh(list(positions), list(values),
            color=[PALETTE[i % len(PALETTE)] for i in positions])
    ax.set_yticks(list(positions))
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title, fontsize=12, fontweight="bold")
    return figure(title, to_png(fig))


def scatter_layout(title, positions, labels=None, circles=None,
                   width=6.0, height=6.0) -> dict:
    """Plan view of a multirotor frame: motor positions and prop disks."""
    if not available():
        raise RuntimeError("matplotlib is not installed.")
    fig, ax = new_axes(width, height)

    if circles:
        for (x, y), radius in circles:
            ax.add_patch(_pyplot().Circle((x, y), radius, fill=True, alpha=0.15,
                                          color=PALETTE[0]))
            ax.add_patch(_pyplot().Circle((x, y), radius, fill=False,
                                          color=PALETTE[0], linewidth=1.2))

    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    for x, y in positions:
        ax.plot([0, x], [0, y], color="#7f8c8d", linewidth=2.0, zorder=2)
    ax.plot(xs, ys, "o", color=PALETTE[1], markersize=10, zorder=3)
    ax.plot([0], [0], "s", color="#2c3e50", markersize=12, zorder=3)

    for index, (x, y) in enumerate(positions):
        text = labels[index] if labels and index < len(labels) else str(index + 1)
        ax.annotate(text, (x, y), textcoords="offset points", xytext=(9, 9),
                    fontsize=9, fontweight="bold")

    ax.set_aspect("equal")
    ax.set_xlabel("X (m)  -- nose is +X")
    ax.set_ylabel("Y (m)")
    ax.set_title(title, fontsize=12, fontweight="bold")
    return figure(title, to_png(fig))
