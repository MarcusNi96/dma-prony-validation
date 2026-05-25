"""Convert raw DMA .xls files to a single combined CSV per material.

Reads data/raw/<material>/dma/<run>/<*.xls>, applies optional sibling
clean.json filtering and the chamber->sample temperature compensation
(0.7 T_c + 7.5) for tf_* runs, concatenates the chosen runs, and writes
one CSV to data/<material>/dma/<--out>. No metadata.

Clean.json schema (optional sidecar next to each raw .xls):
    {
      "exclude_freq_hz": [50, 100],          # drop these frequencies (all temps)
      "tolerance_hz": 0.001,
      "exclude_temperature_C": [25],         # drop entire isotherms
      "tolerance_C": 1.0,
      "exclude_points": [                    # drop individual (T, f) cells
        {"temperature_C": -25, "freq_hz": 100, "reason": "..."}
      ]
    }

Usage:
    python data/raw/process_dma.py \
        --material epdm_70 \
        --run tf_015p tf_015p_high \
        --out tf_015p.csv
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def convert_xls(xls_path):
    """Read xls, drop units row, return standardized DataFrame with SI columns."""
    df = pd.read_excel(xls_path, engine="xlrd")
    df = df.iloc[1:].reset_index(drop=True)
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return pd.DataFrame({
        "freq_hz": df["f"],
        "temperature_C": df["T"],
        "G_storage_pa": df["G'"] * 1e6,
        "G_loss_pa": df["G''"] * 1e6,
        "G_abs_pa": df["|G*|"] * 1e6,
        "tan_delta": df["tan delta"],
        "force_dyn_N": df["F dyn."],
        "strain_dyn_pct": df["Strain dyn"],
    }).dropna()


def load_clean_config(run_dir):
    p = run_dir / "clean.json"
    if not p.exists():
        return None
    cfg = json.loads(p.read_text())
    return {
        "exclude_freq_hz":       [float(f) for f in cfg.get("exclude_freq_hz", [])],
        "tolerance_hz":          float(cfg.get("tolerance_hz", 0.001)),
        "exclude_temperature_C": [float(T) for T in cfg.get("exclude_temperature_C", [])],
        "tolerance_C":           float(cfg.get("tolerance_C", 1.0)),
        "exclude_points": [
            {"temperature_C": float(pt["temperature_C"]),
             "freq_hz":       float(pt["freq_hz"])}
            for pt in cfg.get("exclude_points", [])
        ],
    }


def apply_clean(df, clean):
    """Return (filtered_df, entries) where entries is a list of
    (description, n_dropped) for each rule in clean.json. Each row in df is
    attributed to at most one rule (first-match wins, in clean.json order:
    freq -> temperature -> point)."""
    entries = []
    if not clean:
        return df, entries
    f = df["freq_hz"].to_numpy()
    T = df["temperature_C"].to_numpy()
    claimed = np.zeros(len(df), dtype=bool)

    for excl in clean["exclude_freq_hz"]:
        hit = (np.abs(f - excl) <= clean["tolerance_hz"]) & ~claimed
        entries.append((f"exclude_freq_hz {excl}", int(hit.sum())))
        claimed |= hit

    for excl in clean["exclude_temperature_C"]:
        hit = (np.abs(T - excl) <= clean["tolerance_C"]) & ~claimed
        entries.append((f"exclude_temperature_C {excl}", int(hit.sum())))
        claimed |= hit

    for pt in clean["exclude_points"]:
        hit = ((np.abs(f - pt["freq_hz"])       <= clean["tolerance_hz"]) &
               (np.abs(T - pt["temperature_C"]) <= clean["tolerance_C"]) &
               ~claimed)
        entries.append(
            (f"exclude_points T={pt['temperature_C']}, f={pt['freq_hz']}", int(hit.sum())),
        )
        claimed |= hit

    return df[~claimed].reset_index(drop=True), entries


def process_run(material, run):
    run_dir = REPO_ROOT / "data" / "raw" / material / "dma" / run
    xls_files = list(run_dir.glob("*.xls"))
    if not xls_files:
        raise SystemExit(f"{material}/{run}: no .xls file in {run_dir}")
    if len(xls_files) > 1:
        raise SystemExit(f"{material}/{run}: multiple .xls files: {[f.name for f in xls_files]}")
    df = convert_xls(xls_files[0])
    n_raw = len(df)
    clean = load_clean_config(run_dir)
    df, entries = apply_clean(df, clean)
    if run.startswith("tf_"):
        df["temperature_C"] = 0.7 * df["temperature_C"] + 7.5
    df.insert(0, "run", run)

    total_dropped = sum(n for _, n in entries)
    if clean is None:
        print(f"  {run}: {n_raw} raw -> {len(df)} kept (no clean.json)")
    else:
        print(f"  {run}: {n_raw} raw -> {len(df)} kept (dropped {total_dropped})")
        for desc, n in entries:
            print(f"      {n:>3}  {desc}")
    return df


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--material", required=True)
    p.add_argument("--run", required=True, nargs="+",
                   help="One or more run names; their data will be concatenated.")
    p.add_argument("--out", required=True,
                   help="Output filename (e.g. tf_015p.csv); written to data/<material>/dma/.")
    args = p.parse_args()

    frames = [process_run(args.material, r) for r in args.run]
    combined = pd.concat(frames, ignore_index=True)

    out_path = REPO_ROOT / "data" / args.material / "dma" / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False)
    print(f"{args.material}: {len(combined)} rows from {len(args.run)} run(s) "
          f"({', '.join(args.run)}) -> {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
