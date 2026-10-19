"""Noninteractive Agg charts; safe inside the frozen Qt application."""
from io import BytesIO


def chart_png(run, candidate, kind, axes=(0, 1)):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(8, 3), tight_layout=True)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    if kind == "Mass breakdown":
        data = candidate["mass_breakdown"]
        ax.bar(list(data), list(data.values()))
        ax.set_ylabel("Mass (kg)")
    elif kind == "Constraint margins":
        data = candidate["margins"]
        ax.barh(list(data), list(data.values()), color=["#287d50" if v >= 0 else "#bb3333" for v in data.values()])
        ax.axvline(0, color="black", linewidth=.7)
        ax.set_xlabel("Normalized margin (nonnegative is feasible)")
        ax.tick_params(axis="y", labelsize=7)
    elif kind == "Convergence":
        rows = [r for r in run.get("history", []) if r["feasible"]]
        best, ys = float("inf"), []
        for r in rows:
            best = min(best, r["objectives"][0])
            ys.append(best)
        ax.plot([r["evaluation"] for r in rows], ys)
        ax.set(xlabel="Evaluation", ylabel="Best feasible scaled objective")
    elif kind == "Pareto":
        rows = [r for r in run.get("candidates", []) if r["feasible"] and len(r["objectives"]) > 1]
        x, y = axes
        if x == y or any(max(x, y) >= len(r["objectives"]) for r in rows):
            raise ValueError("Choose two distinct objective axes present in this study")
        ax.scatter([r["objectives"][x] for r in rows], [r["objectives"][y] for r in rows])
        ax.set(xlabel=f"Scaled objective {x + 1} (minimize)", ylabel=f"Scaled objective {y + 1} (minimize)")
    elif kind == "Uncertainty":
        rows = [r for r in run.get("candidates", []) if r["valid"] and r["objectives"]]
        ax.hist([r["objectives"][0] for r in rows], bins="auto")
        ax.set(xlabel="Scaled objective 1; valid samples only", ylabel="Sample count")
    else:
        rows = candidate.get("endurance_history", []) if kind == "Endurance mission" else candidate["mission_history"]
        rocket = bool(rows and "thrust" in rows[0])
        field = "energy" if kind == "Mission energy" else "altitude" if rocket else "power"
        ax.plot([r["time"] for r in rows], [r.get(field, 0) for r in rows])
        ax.set(xlabel="Time (s)", ylabel="Energy (J)" if field == "energy" else "Altitude (m)" if rocket else "Shaft power (W)")
    ax.set_title(kind)
    ax.grid(alpha=.2)
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=100)
    return buffer.getvalue()
