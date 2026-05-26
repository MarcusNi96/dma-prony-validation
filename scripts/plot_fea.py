"""Overlay measured vs FEA transmissibility for one shaker experiment.

Reads:
    results/<material>/validation/<experiment>/result.json   FEA history (MassRP A2)
    data/<material>/shaker/<run>.csv                          measured shaker run

Writes:
    results/<material>/validation/<experiment>/transmissibility.png

Transmissibility T = a_mass / a_base.
- Measured: a_base and a_mass both come from the CSV (mag + phase).
- FEA:      a_mass comes from MassRP A2 (complex); a_base is 1 G (the BC),
            so T_fea = a_mass / G_ACCEL.

Usage:
    python scripts/plot_fea.py --material material_a --experiment shaker_1g_ds_33mm_6mm_258g
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from py3.paths import REPO_ROOT, processed_csv

G_ACCEL = 9.81  # m/s^2


# ---------- argparse ----------

def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--material", required=True)
    p.add_argument("--experiment", required=True,
                   help="experiment name, e.g. shaker_1g_ds_33mm_6mm_258g")
    p.add_argument("--shaker-run", default=None,
                   help="processed shaker CSV stem under data/<material>/shaker/. "
                        "Default: --experiment with leading 'shaker_' stripped.")
    return p.parse_args()


# ---------- I/O (boring) ----------

def load_fea(path: Path, region: str = "MASSRP", name: str = "A2"):
    """Read result.json (one HistoryAccess record). Returns (freq_hz, accel_complex)."""
    with path.open() as f:
        records = json.load(f)
    matches = [r for r in records
               if (r.get("region") or "").upper() == region
               and r.get("name") == name]
    if not matches:
        raise SystemExit(f"{path}: no record with region={region!r} name={name!r}; "
                         f"got {[(r.get('region'), r.get('name')) for r in records]}")
    rec = matches[0]
    freqs, reals, imags = [], [], []
    for (f_re, real), (f_im, imag) in zip(rec["data"], rec["conjugate_data"]):
        if f_re != f_im:
            raise SystemExit(f"{path}: data/conjugate_data freq mismatch ({f_re} vs {f_im})")
        freqs.append(f_re)
        reals.append(real)
        imags.append(imag)
    return np.array(freqs), np.array(reals) + 1j * np.array(imags)


def load_measured(path: Path):
    """Read processed shaker CSV. Returns (freq_hz, a_base_complex, a_mass_complex)."""
    df = pd.read_csv(path)
    f = df["freq_hz"].to_numpy()
    a_base = df["base_accel_ms2"].to_numpy() * np.exp(1j * df["base_phase_rad"].to_numpy())
    a_mass = df["mass_accel_ms2"].to_numpy() * np.exp(1j * df["mass_phase_rad"].to_numpy())
    return f, a_base, a_mass


# ---------- plotting ----------

def plot_transmissibility(f_meas, T_meas, f_fea, T_fea, save_path, title=None):
    """Two panels: |T| (top), phase(T) in degrees (bottom)."""
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

    axes[0].plot(f_meas, np.abs(T_meas), color="C0", label="measured")
    axes[0].plot(f_fea,  np.abs(T_fea),  color="C1", linestyle="--", label="FEA")
    axes[0].axhline(1.0, color="k", lw=0.5, alpha=0.4, label="base (|T|=1)")
    axes[0].set_ylabel("|T|  (mass / base accel)")
    axes[0].set_title("Transmissibility magnitude")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()

    phase_meas = np.rad2deg(np.unwrap(np.angle(T_meas)))
    phase_fea  = np.rad2deg(np.unwrap(np.angle(T_fea)))
    axes[1].plot(f_meas, phase_meas, color="C0", label="measured")
    axes[1].plot(f_fea,  phase_fea,  color="C1", linestyle="--", label="FEA")
    axes[1].set_xlabel("frequency (Hz)")
    axes[1].set_ylabel("phase(T) (deg)")
    axes[1].set_title("Transmissibility phase (mass − base, unwrapped)")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()

    if title:
        fig.suptitle(title)
    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150)
    plt.close(fig)


# ---------- glue ----------

def main():
    args = parse_args()

    fea_dir  = REPO_ROOT / "results" / args.material / "validation" / args.experiment
    fea_path = fea_dir / "result.json"
    if not fea_path.exists():
        raise SystemExit(f"FEA result not found: {fea_path}")
    f_fea, a_mass_fea = load_fea(fea_path)
    T_fea = a_mass_fea / G_ACCEL

    shaker_run = (args.shaker_run if args.shaker_run is not None
                  else args.experiment[len("shaker_"):]
                       if args.experiment.startswith("shaker_") else args.experiment)
    meas_path = processed_csv(args.material, "shaker", shaker_run)
    if not meas_path.exists():
        raise SystemExit(f"shaker CSV not found: {meas_path}")
    f_meas, a_base_meas, a_mass_meas = load_measured(meas_path)
    T_meas = a_mass_meas / a_base_meas

    print(f"FEA       : {len(f_fea)} pts, f = {f_fea.min():g} - {f_fea.max():g} Hz "
          f"-> {fea_path.relative_to(REPO_ROOT)}")
    print(f"measured  : {len(f_meas)} pts, f = {f_meas.min():g} - {f_meas.max():g} Hz "
          f"-> {meas_path.relative_to(REPO_ROOT)}")

    out = fea_dir / "transmissibility.png"
    plot_transmissibility(f_meas, T_meas, f_fea, T_fea, save_path=out,
                          title=f"{args.material} / {args.experiment}")
    print(f"-> {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
