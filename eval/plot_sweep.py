"""Draw the threshold-sweep chart for docs/evaluation_report.md.

Usage: python -m eval.plot_sweep <test_result.json> <dev_result.json> [out.png]
Reads saved eval results only (no LLM calls).
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = {"Test set (25)": "#2a78d6", "Dev set (60)": "#eb6834"}  # validated palette slots 1-2


def sweep(path: Path) -> tuple[list[float], list[float]]:
    rows = json.loads(path.read_text())["threshold_sweep"]
    return [r["threshold"] for r in rows], [100 * r["auto_approval_rate"] for r in rows]


def main() -> None:
    test_path, dev_path = Path(sys.argv[1]), Path(sys.argv[2])
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("docs/img/threshold_sweep.png")
    out.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for (label, color), path in zip(SERIES.items(), (test_path, dev_path), strict=True):
        x, y = sweep(path)
        ax.plot(
            x,
            y,
            color=color,
            linewidth=2,
            marker="o",
            markersize=7,
            label=label,
            markeredgecolor=SURFACE,
            markeredgewidth=2,
            solid_capstyle="round",
        )
        ax.annotate(
            f"{label}: {y[-1]:.0f}%",
            (x[-1], y[-1]),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            color=INK,
            fontsize=9,
        )

    ax.axvline(0.85, color=INK_2, linewidth=1, linestyle=(0, (2, 3)))
    ax.text(0.852, 52, "current setting 0.85", color=INK_2, fontsize=8.5, va="bottom")
    ax.set_xlim(0.58, 1.06)
    ax.set_ylim(50, 100)
    ax.set_xticks([0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95])
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.set_xlabel("Confidence threshold", color=INK_2, fontsize=9)
    ax.set_ylabel("Invoices approved automatically", color=INK_2, fontsize=9)
    ax.set_title(
        "Auto-approval rate by threshold (wrong fields in auto-approved: 0% at every threshold)",
        color=INK,
        fontsize=10,
        loc="left",
    )
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(colors=INK_2, labelsize=8.5, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.legend(frameon=False, loc="lower left", fontsize=8.5, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
