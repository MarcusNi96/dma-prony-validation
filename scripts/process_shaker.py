"""Convert raw VibrationVIEW shaker CSV to standardized CSV.

Reads data/raw/<material>/shaker/<run>/<*.csv>, picks the relevant
columns (Ch1 = base, Ch2 = mass, accel in G + phase in rad), converts
G -> m/s^2, writes data/<material>/shaker/<run>.csv.

Usage:
    python scripts/process_shaker.py --material epdm_70 --run 1g_ds_33mm_6mm_573g
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    raise NotImplementedError("scaffold")


if __name__ == "__main__":
    main()
