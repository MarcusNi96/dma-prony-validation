"""Convert raw VibrationVIEW shaker CSV(s) to a single combined CSV per material.

Reads data/raw/<material>/shaker/<run>/<*.csv>. The VibrationVIEW Live
Sine export has ~67 columns with duplicated headers, so we pick by
INDEX (first occurrence). Converts G -> m/s^2; phases stay in rad.

Usage:
    python data/raw/process_shaker.py \
        --material epdm_70 \
        --run 1g_ds_33mm_6mm_573g \
        --out 1g_ds_33mm_6mm_573g.csv
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Column indices (first occurrence) in VibrationVIEW Live Sine Test CSV
COL_FREQ         = 0
COL_BASE_ACCEL_G = 7    # Ch1 (G)
COL_MASS_ACCEL_G = 8    # Ch2 (G)
COL_BASE_PHASE   = 31   # Ch1 Phase (rad)
COL_MASS_PHASE   = 32   # Ch2 Phase (rad)

G_ACCEL = 9.81  # m/s^2


def convert_csv(csv_path):
    """Read one VibrationVIEW CSV, return the standardized 5-column DataFrame."""
    raw = pd.read_csv(csv_path)
    df = pd.DataFrame({
        "freq_hz":        raw.iloc[:, COL_FREQ],
        "base_accel_ms2": raw.iloc[:, COL_BASE_ACCEL_G] * G_ACCEL,
        "base_phase_rad": raw.iloc[:, COL_BASE_PHASE],
        "mass_accel_ms2": raw.iloc[:, COL_MASS_ACCEL_G] * G_ACCEL,
        "mass_phase_rad": raw.iloc[:, COL_MASS_PHASE],
    })
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna().reset_index(drop=True)


def process_run(material, run):
    run_dir = REPO_ROOT / "data" / "raw" / material / "shaker" / run
    csvs = list(run_dir.glob("*.csv"))
    if not csvs:
        raise SystemExit(f"{material}/{run}: no .csv file in {run_dir}")
    if len(csvs) > 1:
        raise SystemExit(f"{material}/{run}: multiple .csv files: {[f.name for f in csvs]}")
    df = convert_csv(csvs[0])
    df.insert(0, "run", run)
    print(f"  {run}: {len(df)} rows, "
          f"f = {df['freq_hz'].min():g} - {df['freq_hz'].max():g} Hz")
    return df


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--material", required=True)
    p.add_argument("--run", required=True, nargs="+",
                   help="One or more run names; their data will be concatenated.")
    p.add_argument("--out", required=True,
                   help="Output filename (e.g. 1g_ds_33mm_6mm_573g.csv); "
                        "written to data/<material>/shaker/.")
    args = p.parse_args()

    frames = [process_run(args.material, r) for r in args.run]
    combined = pd.concat(frames, ignore_index=True)

    out_path = REPO_ROOT / "data" / args.material / "shaker" / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False)
    print(f"{args.material}: {len(combined)} rows from {len(args.run)} run(s) "
          f"({', '.join(args.run)}) -> {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
