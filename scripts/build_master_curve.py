"""Build a TTS master curve from a processed DMA combined CSV.

Reads data/<material>/dma/<run>.csv (output of data/raw/process_dma.py),
groups rows into per-temperature isotherms, shifts them onto T_ref, fits
WLF on the shift factors, writes:

    results/<material>/master/master_curve.csv     freq_hz, G_storage_pa, G_loss_pa
    results/<material>/master/wlf.json             {C1, C2, T_ref}
    results/<material>/master/diagnostic.png       3-panel diagnostic

Usage:
    python scripts/build_master_curve.py --material epdm_70 --run tf_015p --ref-temp 25
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from mastercurves import MasterCurve
from mastercurves.transforms import Multiply
from scipy.optimize import curve_fit

from core.plots import plot_master_curve_diagnostic
from py3.paths import REPO_ROOT, master_dir, processed_csv


# ----------------- I/O & grouping (boring) -----------------

def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--material", required=True)
    p.add_argument("--run", required=True,
                   help="Processed CSV name under data/<material>/dma/ (e.g. tf_015p)")
    p.add_argument("--ref-temp", type=float, default=25.0,
                   help="Reference temperature for the master curve, °C.")
    p.add_argument("--on-loss", action="store_true",
                   help="Shift on G'' (loss) instead of G' (storage).")
    return p.parse_args()


def load_isotherms(material, run):
    """Read the combined CSV and group rows into per-temperature isotherms.

    Returns four parallel lists, sorted ascending by temperature:
        freq_per_T[k]  : 1-D array of freq_hz for isotherm k
        gp_per_T[k]    : 1-D array of G_storage_pa
        gpp_per_T[k]   : 1-D array of G_loss_pa
        temps_C[k]     : float, nominal temperature in °C
    """
    df = pd.read_csv(processed_csv(material, "dma", run))
    df["T_round"] = df["temperature_C"].round().astype(int)

    freq_per_T, gp_per_T, gpp_per_T, temps_C = [], [], [], []
    for T in sorted(df["T_round"].unique()):
        sub = df[df["T_round"] == T].sort_values("freq_hz")
        freq_per_T.append(sub["freq_hz"].to_numpy())
        gp_per_T.append(sub["G_storage_pa"].to_numpy())
        gpp_per_T.append(sub["G_loss_pa"].to_numpy())
        temps_C.append(float(T))
    return freq_per_T, gp_per_T, gpp_per_T, temps_C


def save_master_csv(out_path, freq, gp, gpp):
    order = np.argsort(freq)
    pd.DataFrame({
        "freq_hz":       freq[order],
        "G_storage_pa":  gp[order],
        "G_loss_pa":     gpp[order],
    }).to_csv(out_path, index=False)


def save_wlf_json(out_path, C1, C2, ref_temp):
    out_path.write_text(json.dumps(
        {"C1": float(C1), "C2": float(C2), "T_ref_C": float(ref_temp)}, indent=2
    ))

# ----------------- glue -----------------

def main():
    args = parse_args()
    freq_per_T, gp_per_T, gpp_per_T, temps_C = load_isotherms(args.material, args.run)
    print(f"{args.material}/{args.run}: {len(temps_C)} isotherms {temps_C}")

    ### Main part
    mc = MasterCurve()

    freq_per_T_log = [np.log(f) for f in freq_per_T]
    gp_per_T_log = [np.log(f) for f in gp_per_T]
    gpp_per_T_log = [np.log(f) for f in gpp_per_T]

    if args.on_loss:
        mc.add_data(freq_per_T_log, gpp_per_T_log, temps_C)
    else:
        mc.add_data(freq_per_T_log, gp_per_T_log, temps_C)


    mc.add_htransform(Multiply(scale="log"))
    mc.superpose()

    mc.change_ref(args.ref_temp)

    a_T = mc.hparams[0]
    

    def wlf(T, C_1, C_2):
        return -C_1 * (T - args.ref_temp) / (C_2 + T - args.ref_temp)

    initial_guess = [17.4, 51.6] #From original paper
    bounds = ([0, 0], [1000.0, 1000.0])

    parameters,_ = curve_fit(wlf, temps_C, np.log10(a_T), p0=initial_guess, bounds=bounds)
    C1, C2 = parameters

    print(f"WLF: C1={C1:.3f}, C2={C2:.3f} (T_ref={args.ref_temp} °C)")

    freq_shifted_per_T= []
    for k in range(len(freq_per_T)):
        freq_shifted_per_T.append(freq_per_T[k] * a_T[k])


    # concat and sort by shifted frequency
    freq_master = np.concatenate(freq_shifted_per_T)
    gp_master   = np.concatenate(gp_per_T)
    gpp_master  = np.concatenate(gpp_per_T)

    order = np.argsort(freq_master)
    freq_master, gp_master, gpp_master = freq_master[order], gp_master[order], gpp_master[order]

    out_dir = master_dir(args.material)
    out_dir.mkdir(parents=True, exist_ok=True)
    save_master_csv(out_dir / "master_curve.csv", freq_master, gp_master, gpp_master)
    save_wlf_json(out_dir / "wlf.json", C1, C2, args.ref_temp)
    
    plot_master_curve_diagnostic(
        freq_per_T, gp_per_T, gpp_per_T, temps_C,
        a_T, args.ref_temp,
        wlf=(C1, C2),
        save_path=out_dir / "diagnostic.png",
    )


    print(f"-> {out_dir.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
