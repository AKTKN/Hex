import sys
import csv
from pathlib import Path
import pandas as pd
# show more columns
pd.set_option("display.max_columns", None)
pd.set_option("display.width", None)
pd.set_option("display.expand_frame_repr", False)
from plotting_lib import generate_threshold_plot
import numpy as np

def main():
    if len(sys.argv) < 2:
        print("Error: summary.csv path required as argument", file=sys.stderr)
        return 1
    summary_csv_path = Path(sys.argv[1])

    if not summary_csv_path.exists():
        print(f"Error: {summary_csv_path} not found", file=sys.stderr)
        return 1

    summary_df = pd.read_csv(summary_csv_path, dtype={"distance": int})

    def label_function(row):
        return pd.Series({
            # "label": f"Distance = {int(row.distance)}, Repetitions = {int(row.repetitions)}, Include Corrections = {row.include_corrections}"
            "label": r"[\![" + f"{int(row.distance)**2},1,{int(row.distance)}" + r"]\!]"
        })
    for (code, offline_decoder, online_decoder, num_teleportations), group in summary_df.groupby(["code", "online_decoder", "offline_decoder", "num_teleportations"]):
        plotting_df = pd.DataFrame(columns=["physical error", "logical error", "logical error interval above", "logical error interval below", "label"])


        pauli = group["pauli"].unique().tolist()
        if len(pauli) != 1:
            print("Can only plot one type of Pauli")

            return 1
        else:
            z = 1.96
            group["logical_errors_prime"] = group["logical_errors"] + z
            group["samples_performed_prime"] = group["samples_performed"] + z**2
            group["logical_error_rate_prime"] = group["logical_errors_prime"] / group["samples_performed_prime"]
            group["error_bar"] = z*np.sqrt((group["logical_error_rate_prime"] * (1 - group["logical_error_rate_prime"])) / group["samples_performed_prime"]
                                              )

            plotting_df["physical error"] = group["physical_error_rate"]
            plotting_df["logical error"] = group["logical_error_rate_prime"]
            plotting_df["logical error interval above"] = group["error_bar"]
            plotting_df["logical error interval below"] = group["error_bar"]
            plotting_df["label"] = group.apply(label_function, axis=1)

            # Generate CSV for plotting
            plotting_df.to_csv(f"plotting_data_code={code}_online_decoder={online_decoder}_offline_decoder={offline_decoder}_num_teleportations={num_teleportations}.csv", index=False)
            # title = f"Steane EC Memory Experiment, Measuring logical {'Z' if (pauli[0].lower() == 'z') else 'X'}"
            title = f"Threshold Plot"
            generate_threshold_plot(
                f"plotting_data_code={code}_online_decoder={online_decoder}_offline_decoder={offline_decoder}_num_teleportations={num_teleportations}.csv",
                title,
                style="Quantum",
                output_path=f"plotting_data_code={code}_online_decoder={online_decoder}_offline_decoder={offline_decoder}_num_teleportations={num_teleportations}.pdf",
            )

    return 0

if __name__ == '__main__':
    sys.exit(main())
