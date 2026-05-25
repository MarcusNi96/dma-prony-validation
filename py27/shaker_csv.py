"""Tiny stdlib-only CSV reader for shaker data - no pandas (Py27).

Reads the standardized processed shaker schema:
    freq_hz, base_accel_ms2, base_phase_rad, mass_accel_ms2, mass_phase_rad

Values are already in SI (m/s^2, rad) - no unit conversion here. The base
acceleration is what we feed Abaqus as the boundary condition.
"""
import csv


def read_base_accel(csv_path):
    """Return (freq_hz_list, base_accel_ms2_list) sorted by frequency.

    Both lists are plain Python floats - no numpy in Abaqus's Py27.
    """
    freq = []
    accel = []
    f = open(csv_path, "r")
    try:
        reader = csv.DictReader(f)
        for row in reader:
            freq.append(float(row["freq_hz"]))
            accel.append(float(row["base_accel_ms2"]))
    finally:
        f.close()

    pairs = sorted(zip(freq, accel))
    return [p[0] for p in pairs], [p[1] for p in pairs]
