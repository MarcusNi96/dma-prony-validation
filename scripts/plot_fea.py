"""Compare FEA prediction to measured shaker transmissibility.

Reads:
    - results/<material>/fea/<test>/<exp>/results.json   (Abaqus history)
    - data/<material>/shaker/<run>.csv                    (measured)

Writes (to the same FEA results dir):
    - transmissibility.png      |T| and phase, exp + FEA
    - frf.png                   3x4 accelerance/mobility/compliance grid
    - mass_accel.csv            FEA mass accel in same schema as measured shaker CSV

Usage:
    python scripts/plot_fea.py --material epdm_70 --experiment shaker_1g_ds_33mm_6mm_573g
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    raise NotImplementedError("scaffold")


if __name__ == "__main__":
    main()
