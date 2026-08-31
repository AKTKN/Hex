"""Plot saved Knill reproducibility comparisons without running simulations."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Mapping, Sequence


def read_comparison(path: Path) -> list[dict[str, str]]:
    """Read a comparison CSV previously produced by a validation runner."""

    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def plot_comparison(
    rows: Sequence[Mapping[str, object]],
    output_base: Path,
    *,
    legacy_label: str,
    new_label: str,
    log_scale: bool = True,
) -> tuple[Path, Path]:
    """Create a distance-panel LER figure from pooled comparison rows."""

    import matplotlib.pyplot as plt

    distances = sorted({int(row["distance"]) for row in rows})
    if not distances:
        raise ValueError("comparison data is empty")
    figure, axes = plt.subplots(
        1, len(distances), squeeze=False, figsize=(5.2 * len(distances), 4.2),
        sharey=True,
    )
    axes_flat = axes[0]
    colours = {legacy_label: "tab:blue", new_label: "tab:orange"}
    markers = {legacy_label: "o", new_label: "s"}
    for axis, distance in zip(axes_flat, distances):
        distance_rows = [row for row in rows if int(row["distance"]) == distance]
        for label, shots_key, ler_key, low_key, high_key in (
            (legacy_label, "legacy_shots", "legacy_ler", "legacy_ci_low", "legacy_ci_high"),
            (new_label, "new_shots", "new_ler", "new_ci_low", "new_ci_high"),
        ):
            selected = sorted(distance_rows, key=lambda row: float(row["physical_error"]))
            x = [float(row["physical_error"]) for row in selected]
            y = [float(row[ler_key]) for row in selected]
            # A log axis cannot display an exact zero.  Keep zero-count points
            # visible at a finite floor while retaining their upper interval.
            positive = [value for value in y if value > 0]
            floor = min(positive) / 2 if positive else 1e-6
            plotted_y = [value if value > 0 else floor for value in y]
            lower = [max(0.0, value - float(row[low_key])) for value, row in zip(plotted_y, selected)]
            upper = [max(0.0, float(row[high_key]) - value) for value, row in zip(plotted_y, selected)]
            axis.errorbar(
                x,
                plotted_y,
                yerr=[lower, upper],
                label=label,
                color=colours[label],
                marker=markers[label],
                linestyle="-",
                capsize=3,
            )
        axis.set_title(f"Surface code distance {distance}")
        axis.set_xlabel("physical error rate")
        axis.grid(True, which="both", alpha=0.25)
        if log_scale:
            axis.set_yscale("log")
    axes_flat[0].set_ylabel("logical error rate")
    axes_flat[-1].legend()
    figure.tight_layout()
    output_base.parent.mkdir(parents=True, exist_ok=True)
    png_path = output_base.with_suffix(".png")
    pdf_path = output_base.with_suffix(".pdf")
    figure.savefig(png_path, dpi=160)
    figure.savefig(pdf_path)
    plt.close(figure)
    return png_path, pdf_path


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("validation/results"))
    parser.add_argument("--all", action="store_true", help="plot both validation suites")
    parser.add_argument("--validation", choices=("fixed", "adaptive"))
    parser.add_argument("--linear", action="store_true", help="use a linear LER axis")
    args = parser.parse_args(argv)
    if not args.all and args.validation is None:
        parser.error("choose --all or --validation fixed|adaptive")
    choices = ("fixed", "adaptive") if args.all else (args.validation,)
    for choice in choices:
        if choice == "fixed":
            filename = "fixed_workflow_comparison.csv"
            output = args.output_dir / "figures" / "fixed_workflow_repro"
            labels = ("legacy_static", "stateful_fixed")
        else:
            filename = "adaptive_forced_long_comparison.csv"
            output = args.output_dir / "figures" / "adaptive_forced_long_repro"
            labels = ("legacy_static_fixed_d", "adaptive_forced_long")
        path = args.output_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"comparison CSV not found: {path}")
        plot_comparison(
            read_comparison(path), output,
            legacy_label=labels[0], new_label=labels[1], log_scale=not args.linear,
        )


if __name__ == "__main__":
    main()

