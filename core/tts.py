"""Time-temperature superposition: build a master curve at T_ref.

Reads a multi-temperature DMA CSV (standardized schema), runs
mastercurves.MasterCurve to find horizontal shifts, returns
shifted+merged master curve data anchored at the chosen T_ref.

Does NOT fit Prony. Does NOT plot. Does NOT extrapolate the shift
factors to other temperatures (no WLF/Arrhenius).

Reference: https://krlennon-mastercurves.readthedocs.io/
"""
import numpy as np
import pandas as pd
from mastercurves import MasterCurve
from mastercurves.transforms import Multiply
from scipy.optimize import curve_fit


def load_tf_sweep(csv_path):
    """Read processed DMA CSV and group rows into per-temperature sweeps.

    Each frequency sweep is a contiguous block of rows where the DMA cycles
    through its frequency list at one nominal temperature setpoint. Block
    boundaries are detected by frequency resets (next freq < current freq)
    and each block's representative temperature is the median measured T
    rounded to the nearest degree (DMA isotherms drift ~0.5 to 1 °C; the
    nominal setpoint is what we want to label them with).

    Columns expected: freq_hz, temperature_C, G_storage_pa, G_loss_pa.

    Returns (freq_per_T, gp_per_T, gpp_per_T, temps_C). temps_C is a list
    of floats holding integer-valued degrees C, one per block.
    """
    df = pd.read_csv(csv_path)
    freq = df["freq_hz"].to_numpy()
    temp = df["temperature_C"].to_numpy()
    gp = df["G_storage_pa"].to_numpy()
    gpp = df["G_loss_pa"].to_numpy()

    n = len(freq)
    block_id = np.zeros(n, dtype=int)
    for i in range(1, n):
        block_id[i] = block_id[i - 1] + (1 if freq[i] < freq[i - 1] else 0)

    freq_per_T, gp_per_T, gpp_per_T, temps_C = [], [], [], []
    for b in range(block_id.max() + 1):
        mask = block_id == b
        order = np.argsort(freq[mask])
        freq_per_T.append(freq[mask][order])
        gp_per_T.append(gp[mask][order])
        gpp_per_T.append(gpp[mask][order])
        temps_C.append(float(round(np.median(temp[mask]))))

    return freq_per_T, gp_per_T, gpp_per_T, temps_C


def build_master_curve(freq_per_T, modulus_per_T, temps_C, ref_temp=25.0):
    """Horizontal-shift onto a master curve, anchored at ref_temp.

    ref_temp must be one of the measured temperatures in temps_C.

    Returns the MasterCurve object (use .hparams[0] for the per-T shifts).
    """
    if ref_temp not in temps_C:
        raise ValueError(
            f"ref_temp {ref_temp} °C is not in measured temperatures {temps_C}"
        )

    log_x = [np.log(f) for f in freq_per_T]
    log_y = [np.log(g) for g in modulus_per_T]

    mc = MasterCurve()
    mc.add_data(log_x, log_y, temps_C)
    mc.add_htransform(Multiply(scale="log"))
    mc.superpose()
    mc.change_ref(ref_temp)
    return mc

def fit_wlf(shift_factos, temperatures, ref_temp):
    
    def wlf(T, C_1, C_2):
        return -C_1 * (T - ref_temp) / (C_2 + T - ref_temp)

    initial_guess = [17.4, 51.6]
    bounds = ([0, 0], [1000.0, 1000.0])

    parameters,_ = curve_fit(wlf, temperatures, np.log10(shift_factos), p0=initial_guess, bounds=bounds)
    C_1, C_2 = parameters
    return C_1, C_2




def merge_shifted_data(freq_per_T, modulus_per_T, a_T):
    """Apply horizontal shifts and concatenate into a single master curve.

    All channels (G' and G'') receive the same shift — TTS is a property of
    the material relaxation spectrum, not of one channel.
    """
    f_master = np.concatenate([f * a for f, a in zip(freq_per_T, a_T)])
    g_master = np.concatenate(modulus_per_T)
    order = np.argsort(f_master)
    return f_master[order], g_master[order]


def save_master_curve_csv(out_path, freq_master_hz, gp_master_pa, gpp_master_pa):
    """Write the master curve in the standardized schema.

    Columns: freq_hz, G_storage_pa, G_loss_pa. Reference temperature
    lives in the sibling metadata.json.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({
        "freq_hz": freq_master_hz,
        "G_storage_pa": gp_master_pa,
        "G_loss_pa": gpp_master_pa,
    })
    df.to_csv(out_path, index=False)
