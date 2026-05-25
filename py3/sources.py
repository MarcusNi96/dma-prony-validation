"""Typed source loaders — each returns (freq_hz, modulus_complex_pa, label).

Processed CSVs follow standardized schemas (see README "Data layout"):

    DMA:    freq_hz, temperature_C, G_storage_pa, G_loss_pa
    Shaker: freq_hz, base_accel_ms2, base_phase_rad, mass_accel_ms2, mass_phase_rad
    Master: freq_hz, G_storage_pa, G_loss_pa

Loaders here NEVER consult a config to find column names. All values are
SI internally.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from py3 import mechanics
from py3.paths import load_experiment


def _complex_modulus(df):
    return df["G_storage_pa"].to_numpy() + 1j * df["G_loss_pa"].to_numpy()


def load_master(path):
    """Read data/processed/<m>/master/<run>/data.csv. Returns (freq, G*, label)."""
    path = Path(path)
    df = pd.read_csv(path)
    freq = df["freq_hz"].to_numpy()
    G = _complex_modulus(df)
    label = f"master/{path.parent.name}"
    return freq, G, label


def load_dma(path):
    """Read data/processed/<m>/dma/<run>/data.csv. Returns (freq, G*, label).

    Refuses multi-temperature data — feeding a TF sweep directly would mix
    temperatures into one Prony fit. Build a master curve first.
    """
    path = Path(path)
    df = pd.read_csv(path)
    temps = sorted({int(t) for t in df["temperature_C"].round()})
    if len(temps) > 1:
        raise ValueError(
            f"DMA source {path} spans multiple temperatures {temps}. "
            "Build a master curve first (scripts/build_master_curve.py) and "
            "load_master that, or filter to one temperature before fitting."
        )
    freq = df["freq_hz"].to_numpy()
    G = _complex_modulus(df)
    label = f"dma/{path.parent.name}"
    return freq, G, label


def load_shaker(path):
    """Read processed shaker CSV. Returns (freq, G*, label).

    Reads sibling metadata.json for the experiment_config name, loads that
    config (mass_kg + double-shear geometry), constructs complex base/mass
    accelerations, runs the mechanics pipeline (accel -> F/x -> stress/strain
    -> complex modulus).
    """
    path = Path(path)
    df = pd.read_csv(path)
    meta = json.loads((path.parent / "metadata.json").read_text())
    exp = load_experiment(meta["experiment_config"])

    freq = df["freq_hz"].to_numpy()
    accel_base = mechanics.construct_complex_phasor(
        df["base_accel_ms2"].to_numpy(), df["base_phase_rad"].to_numpy()
    )
    accel_mass = mechanics.construct_complex_phasor(
        df["mass_accel_ms2"].to_numpy(), df["mass_phase_rad"].to_numpy()
    )

    fd = mechanics.shaker_accelerations_to_force_displacement(
        freq, accel_base, accel_mass, exp["mass_kg"]
    )

    # Double-shear annular specimen: 2 shear faces × annulus area.
    od, id_ = exp["outer_diameter_m"], exp["inner_diameter_m"]
    area = 2 * (np.pi / 4) * (od ** 2 - id_ ** 2)

    ss = mechanics.force_displacment_to_stress_strain(
        fd["force_mass"], fd["displacement_rel"], exp["thickness_m"], area,
        shape_factor=exp.get("shape_factor", 1.0),
    )

    label = f"shaker/{path.parent.name}"
    return freq, ss["modulus"], label


def load_source(path):
    """Dispatch by source-type folder name (data/processed/<m>/<src_type>/<run>/data.csv)."""
    path = Path(path)
    src_type = path.parent.parent.name
    if src_type == "master":
        return load_master(path)
    if src_type == "dma":
        return load_dma(path)
    if src_type == "shaker":
        return load_shaker(path)
    raise ValueError(
        f"Unknown source type {src_type!r}; expected 'dma', 'shaker', or 'master'. "
        f"Path was: {path}"
    )


def load_fea_results(path):
    """Read FEA results.json (written by build_fea_3d_shaker.py), return tidy DataFrame.

    Columns: name, node, region (uppercased — Abaqus uppercases set names in
    the ODB), step, frequency, value (complex).

    Each input record has parallel `data` and `conjugate_data` lists of
    (frequency, real_or_imag) tuples; we pair them by index and assert the
    grids match.
    """
    with open(path) as f:
        records = json.load(f)
    rows = []
    for rec in records:
        region = (rec.get("region") or "").upper()
        for (f_re, real), (f_im, imag) in zip(rec["data"], rec["conjugate_data"]):
            if f_re != f_im:
                raise ValueError(
                    f"FEA results for {rec.get('name')!r}/{rec.get('node')} have "
                    f"mismatched data/conjugate_data freq grids ({f_re} vs {f_im})"
                )
            rows.append({
                "name": rec["name"],
                "node": rec.get("node"),
                "region": region,
                "step": rec.get("step"),
                "frequency": f_re,
                "value": complex(real, imag),
            })
    return pd.DataFrame(rows)
