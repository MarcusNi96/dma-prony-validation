"""Overlay measured vs FEA transmissibility for one shaker experiment.

Reads:
    results/<material>/validation/<experiment>/result_T<temp>.json   one per FEA temperature
    data/<material>/shaker/<run>.csv                                  measured shaker run

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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from py3.paths import REPO_ROOT, load_json, processed_csv

G_ACCEL = 9.81  # m/s^2

RESULT_RE = re.compile(r"result_T(-?\d+)\.json$")


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


# ---------- I/O ----------

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


def discover_fea_results(fea_dir: Path):
    """Return list of (temperature_C, path) sorted ascending by temperature."""
    found = []
    for p in fea_dir.glob("result_T*.json"):
        m = RESULT_RE.search(p.name)
        if m:
            found.append((int(m.group(1)), p))
    found.sort(key=lambda x: x[0])
    return found


# ---------- plotting ----------

def plot_transmissibility(f_meas, T_meas, meas_temp, fea_curves, save_path, title=None):
    """Two panels: |T| (top), phase(T) in degrees (bottom).

    fea_curves: list of (temperature_C, freq, T_complex) sorted by temperature.
    Measured and FEA share one viridis map (purple = cool, yellow = warm)
    spanning all temperatures. Measured is solid; FEA is dashed.
    """
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

    cmap = plt.get_cmap("viridis")
    all_temps = [meas_temp] + [t for t, _, _ in fea_curves]
    t_min, t_max = min(all_temps), max(all_temps)
    span = max(1.0, t_max - t_min)
    meas_color = cmap((meas_temp - t_min) / span)
    fea_colors = [cmap((t - t_min) / span) for t, _, _ in fea_curves]

    axes[0].plot(f_meas, np.abs(T_meas), color=meas_color,
                 label=f"measured {meas_temp:+.0f} °C")
    for (t, f, T), c in zip(fea_curves, fea_colors):
        axes[0].plot(f, np.abs(T), linestyle="--", color=c, label=f"FEA {t:+d} °C")
    axes[0].axhline(1.0, color="k", lw=0.5, alpha=0.4)
    axes[0].set_ylabel("|T|  (mass / base accel)")
    axes[0].set_title(f"Transmissibility magnitude, {title}" if title
                      else "Transmissibility magnitude")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(fontsize=8, ncol=2)

    phase_meas = np.rad2deg(np.unwrap(np.angle(T_meas)))
    axes[1].plot(f_meas, phase_meas, color=meas_color,
                 label=f"measured {meas_temp:+.0f} °C")
    for (t, f, T), c in zip(fea_curves, fea_colors):
        phase = np.rad2deg(np.unwrap(np.angle(T)))
        axes[1].plot(f, phase, linestyle="--", color=c, label=f"FEA {t:+d} °C")
    axes[1].set_xlabel("frequency (Hz)")
    axes[1].set_ylabel("phase(T) (deg)")
    axes[1].set_title("Transmissibility phase (mass − base)")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(fontsize=8, ncol=2)

    fig.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150)
    plt.close(fig)


# ---------- glue ----------

def main():
    args = parse_args()

    fea_dir = REPO_ROOT / "results" / args.material / "validation" / args.experiment
    found = discover_fea_results(fea_dir)
    if not found:
        raise SystemExit(f"No result_T*.json files found in {fea_dir}")

    shaker_cfg = load_json(f"config/shaker/{args.experiment}.json")
    meas_temp = float(shaker_cfg["temperature"])

    fea_curves = []
    for temp_c, path in found:
        f_fea, a_mass_fea = load_fea(path)
        T_fea = a_mass_fea / G_ACCEL
        fea_curves.append((temp_c, f_fea, T_fea))
        print(f"FEA T={temp_c:+d}°C: {len(f_fea)} pts, "
              f"f = {f_fea.min():g} - {f_fea.max():g} Hz "
              f"-> {path.relative_to(REPO_ROOT)}")

    shaker_run = (args.shaker_run if args.shaker_run is not None
                  else args.experiment[len("shaker_"):]
                       if args.experiment.startswith("shaker_") else args.experiment)
    meas_path = processed_csv(args.material, "shaker", shaker_run)
    if not meas_path.exists():
        raise SystemExit(f"shaker CSV not found: {meas_path}")
    f_meas, a_base_meas, a_mass_meas = load_measured(meas_path)
    T_meas = a_mass_meas / a_base_meas
    print(f"measured  : {len(f_meas)} pts, f = {f_meas.min():g} - {f_meas.max():g} Hz "
          f"-> {meas_path.relative_to(REPO_ROOT)}")

    # "epdm_70" -> "EPDM 70"; "1g_573g" -> "1G 573g" (accel in G, mass in g).
    material_pretty = args.material.replace("_", " ").upper()
    cfg_parts = args.experiment.split("_")
    config_pretty = " ".join([cfg_parts[0].upper()] + cfg_parts[1:])
    pretty = f"{material_pretty} {config_pretty}"
    out = fea_dir / "transmissibility.png"
    plot_transmissibility(f_meas, T_meas, meas_temp, fea_curves, save_path=out,
                          title=pretty)
    print(f"-> {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
