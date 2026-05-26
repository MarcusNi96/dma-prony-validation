"""NNLS Prony-series fit on a master curve.

Reads results/<material>/master/master_curve.csv, fits N Maxwell terms,
writes:

    results/<material>/abaqus_input.json    {base:{nu, rho, G_inf}, G_inf,
                                             prony:{g_i, tau_i}, wlf, source}
    results/<material>/prony_fit/fit.png    G' / G'' measured + fit overlay
    results/<material>/prony_fit/fit_data.csv   freq + measured + fit

G_inf precedence:
    --g-inf X       fix G_inf to X
    --fit-g-inf     ignore base.json and fit G_inf as a free NNLS parameter
    (default)       use config/<material>/base.json's G_inf if present,
                    otherwise fit it free.

Usage:
    python scripts/fit_prony.py --material epdm_70 --n-terms 15
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from py3.plots import plot_master_curve_fit
from py3.paths import (
    REPO_ROOT, abaqus_input_path, load_json,
    master_dir, prony_fit_dir,
)


# ----------------- I/O (boring) -----------------

def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--material", required=True)
    p.add_argument("--n-terms", type=int, default=15,
                   help="Number of Maxwell terms in the NNLS fit.")
    p.add_argument("--g-inf", type=float, default=None,
                   help="Fix G_inf to this value (overrides base.json).")
    p.add_argument("--fit-g-inf", action="store_true",
                   help="Ignore base.json's G_inf and fit it as a free NNLS parameter. "
                        "Mutually exclusive with --g-inf.")
    args = p.parse_args()
    if args.fit_g_inf and args.g_inf is not None:
        raise SystemExit("--fit-g-inf and --g-inf are mutually exclusive")
    return args


def load_master(material):
    """Read results/<material>/master/master_curve.csv. Returns (freq_hz, G_complex)."""
    df = pd.read_csv(master_dir(material) / "master_curve.csv").sort_values("freq_hz")
    freq = df["freq_hz"].to_numpy()
    G = df["G_storage_pa"].to_numpy() + 1j * df["G_loss_pa"].to_numpy()
    return freq, G


def resolve_g_inf(args, base):
    """Apply the precedence rules and return (g_inf_or_None, origin_label)."""
    if args.g_inf is not None:
        return args.g_inf, "--g-inf"
    if args.fit_g_inf:
        return None, "--fit-g-inf (free NNLS parameter)"
    g_inf = base.get("G_inf")
    if g_inf is None:
        return None, "(none provided; free NNLS parameter)"
    return float(g_inf), f"config/{args.material}/base.json"


def save_abaqus_input(material, base, G_inf, G_ins, g_i, tau_i, source_info, wlf=None):
    out = {
        "base":  base,                   # verbatim copy of config/<material>/base.json
        "prony": {
            # G_inf and G_ins are the values that normalized this series:
            # g_i = G_i / G_ins, with G_ins = G_inf + sum(G_i).
            "G_inf": float(G_inf),
            "G_ins": float(G_ins),
            "g_i":   [float(g) for g in g_i],
            "tau_i": [float(t) for t in tau_i],
        },
        "source": source_info,
    }
    if wlf is not None:
        out["wlf"] = {
            "C1":      float(wlf["C1"]),
            "C2":      float(wlf["C2"]),
            "T_ref_C": float(wlf["T_ref_C"]),
        }
    abaqus_input_path(material).write_text(json.dumps(out, indent=2))


def save_fit_data_csv(out_path, freq, modulus_meas, modulus_fit):
    pd.DataFrame({
        "freq_hz":          freq,
        "G_storage_meas":   modulus_meas.real,
        "G_loss_meas":      modulus_meas.imag,
        "G_storage_fit":    modulus_fit.real,
        "G_loss_fit":       modulus_fit.imag,
    }).to_csv(out_path, index=False)


# ----------------- glue -----------------

def main():
    args = parse_args()

    freq, G_meas = load_master(args.material)
    print(f"{args.material}: master curve, {len(freq)} points, "
          f"f = {freq.min():g} - {freq.max():g} Hz")

    # Read base.json + wlf.json once; pass into resolve_g_inf and save_abaqus_input.
    base = load_json(f"config/{args.material}/base.json")
    wlf_path = master_dir(args.material) / "wlf.json"
    wlf = json.loads(wlf_path.read_text()) if wlf_path.exists() else None

    G_inf, origin = resolve_g_inf(args, base)

    ### Main part


    omega_k =   2*np.pi*freq

    omega_min = omega_k[0]
    omega_max = omega_k[-1]

    log_start = np.log10(omega_min) - 1
    log_stop = np.log10(omega_max) + 1

    omega_i = np.logspace(log_start, log_stop, args.n_terms)
    tau_i = 1.0 / omega_i

    x = omega_k[:, None] * tau_i[None, :]            # (K, i_terms)
    B = (x ** 2 + 1j * x) / (1 + x ** 2)             # (K, i_terms)

    w = np.abs(G_meas)

    if G_inf is None:
        print(f"G_inf: free NNLS parameter  [{origin}]")
        A_re = np.c_[np.ones_like(omega_k), B.real] / w[:, None]   # (m, N+1)
        A_im = np.c_[np.zeros_like(omega_k), B.imag] / w[:, None]  # (m, N+1)
        A = np.r_[A_re, A_im]
        b = np.r_[G_meas.real / w, G_meas.imag / w]
        sol, _ = nnls(A, b)
        G_inf = float(sol[0])
        G_i = sol[1:]
    else:
        print(f"G_inf: {G_inf:.4e} Pa  [{origin}]")
        A = np.r_[B.real / w[:, None], B.imag / w[:, None]]
        b = np.r_[(G_meas.real-G_inf) / w, G_meas.imag / w]
        G_i, _ = nnls(A, b)



    G_fit = G_inf + np.sum(G_i * B, axis=1)

    G_ins = G_inf + np.sum(G_i)

    g_i = G_i/G_ins

    

    # Save outputs
    fit_dir = prony_fit_dir(args.material)
    fit_dir.mkdir(parents=True, exist_ok=True)
    abaqus_input_path(args.material).parent.mkdir(parents=True, exist_ok=True)

    save_abaqus_input(args.material, base, G_inf, G_ins, g_i, tau_i,
                      source_info={
                          "method": "nnls_maxwell",
                          "n_terms": args.n_terms,
                          "g_inf_origin": origin,
                      },
                      wlf=wlf)
    if wlf:
        print(f"WLF: C1={wlf['C1']:.3f}, C2={wlf['C2']:.3f} K, "
              f"T_ref={wlf['T_ref_C']:.1f} °C  (embedded in abaqus_input.json)")
    save_fit_data_csv(fit_dir / "fit_data.csv", freq, G_meas, G_fit)
    fit_dict = {"G_inf": G_inf, "G_i": G_i, "tau_i": tau_i}
    plot_master_curve_fit(freq, G_meas, fit_dict, save_path=fit_dir / "fit.png",
                          title=f"{args.material} — Prony fit ({args.n_terms} terms)")

    print(f"-> {abaqus_input_path(args.material).relative_to(REPO_ROOT)}")
    print(f"-> {fit_dir.relative_to(REPO_ROOT)}/{{fit.png, fit_data.csv}}")


if __name__ == "__main__":
    main()
