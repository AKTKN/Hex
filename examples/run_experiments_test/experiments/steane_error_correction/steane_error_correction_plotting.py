import sys
import csv
from pathlib import Path
import pandas as pd
from plotting_lib import generate_threshold_plot


def main():
    if len(sys.argv) < 2:
        print("Error: summary.csv path required as argument", file=sys.stderr)
        return 1

    summary_csv_path = Path(sys.argv[1])

    if not summary_csv_path.exists():
        print(f"Error: {summary_csv_path} not found", file=sys.stderr)
        return 1

    summary_df = pd.read_csv(summary_csv_path, dtype={"distance": int})

    plotting_df = pd.DataFrame(columns=["physical error", "logical error", "logical error interval above", "logical error interval below", "label"])

    def label_function(row):
        return pd.Series({
            "label": f"Distance = {int(row.distance)}, Repetitions = {int(row.repetitions)}, Include Corrections = {row.include_corrections}"
        })

    pauli = summary_df["pauli"].unique().tolist()
    if len(pauli) != 1:
        print("Can only plot one type of Pauli")

        return 1
    else:
        plotting_df["physical error"] = summary_df["physical_error_rate"]
        plotting_df["logical error"] = summary_df["logical_error_rate"]
        plotting_df["logical error interval above"] = 0
        plotting_df["logical error interval below"] = 0
        plotting_df["label"] = summary_df.apply(label_function, axis=1)

        # Generate CSV for plotting
        plotting_df.to_csv(f"plotting_data.csv", index=False)
        title = f"Steane EC Memory Experiment, Measuring logical {'Z' if (pauli[0].lower() == 'z') else 'X'}"
        generate_threshold_plot(
            "plotting_data.csv",
            title,
            output_path=f"{title}.pdf",
        )

        return 0

if __name__ == '__main__':
    sys.exit(main())
