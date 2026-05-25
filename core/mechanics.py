"""Pure mechanics: complex modulus arithmetic, NNLS Maxwell fit, Prony conversion.

No file IO. Inputs and outputs are numpy arrays. The frequency unit is Hz
and the modulus unit is Pa throughout.
"""
from typing import Optional

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import nnls

G_ACCEL = 9.81 # m/s^2 per G


def construct_complex_phasor(magnitude: NDArray, phase_rad: NDArray) -> NDArray:
    """Build a complex phasor from magnitude + phase arrays."""
    return magnitude * np.exp(1j * phase_rad)


def shaker_accelerations_to_force_displacement(
    frequency_hz: NDArray,
    accel_base: NDArray,
    accel_mass: NDArray,
    mass: float,
) -> dict:
    """Convert measured base + mass accelerations into force on the rubber and
    relative displacement across it.

    Sign convention: force on the rubber from the mass is -m*a_mass (Newton's
    third law). Displacement is -accel/omega^2 in the frequency domain.
    """
    omega2 = (2 * np.pi * frequency_hz) ** 2
    force_mass = -accel_mass * mass
    displacement_rel = (accel_mass - accel_base) / (-omega2)
    displacement_base = accel_base / (-omega2)
    displacement_mass = accel_mass / (-omega2)
    return {
        "force_mass": force_mass,
        "displacement_rel": displacement_rel,
        "displacement_base": displacement_base,
        "displacement_mass": displacement_mass,
    }


def force_displacment_to_stress_strain(
    force: NDArray,
    displacement: NDArray,
    thickness: float,
    area: float,
    shape_factor = 1,
) -> dict:
    """Stress = force / area; strain = displacement / thickness; G* = stress / strain."""
    stress = force / (area*shape_factor)
    strain = displacement / thickness
    modulus = stress / strain
    return {"stress": stress, "strain": strain, "modulus": modulus}


def fit_generalized_maxwell_model(
    frequency_hz: NDArray,
    modulus: NDArray,
    n_terms: int,
    G_inf: Optional[float] = None,
) -> dict:
    """Fit a generalized Maxwell model to complex modulus data via NNLS.

    Tau values are placed on a log-spaced grid spanning one decade beyond the
    measurement range on each side. Per-row normalization (by Re/Im of
    modulus) conditions the least-squares problem so high- and low-modulus
    rows contribute comparably.

    G_inf handling:
    - If `G_inf` is given (e.g. from a stress-relaxation measurement) it is
      held fixed and only the Maxwell weights G_i are fit.
    - If `G_inf` is None it becomes a free parameter, prepended as an extra
      non-negative unknown to the NNLS system. G_inf contributes 1 to G'
      and 0 to G'' at every frequency, so the design matrix gets a column
      of ones in the real block and zeros in the imaginary block.

    Returns G_inf (input or fitted), G_i (Maxwell weights, absolute Pa),
    tau_i (relaxation times), and g_fit (the model evaluated at the input
    frequencies — useful for residual computation).
    """
    omega = 2 * np.pi * frequency_hz
    f_min = frequency_hz[0]
    print(f_min)
    f_max = frequency_hz[-1]
    print(f_max)
    log_start = np.log10(f_min) - 1
    log_stop = np.log10(f_max) + 1
    
    f_i = np.logspace(log_start, log_stop, n_terms)
    print(f_i)
    tau_i = 1.0 / (2 * np.pi * f_i)

    x = omega[:, None] * tau_i[None, :]            # (m, N)
    B = (x ** 2 + 1j * x) / (1 + x ** 2)           # (m, N)

    w = np.abs(modulus)

    if G_inf is None:
        A_re = np.c_[np.ones_like(omega), B.real] / w[:, None]   # (m, N+1)
        A_im = np.c_[np.zeros_like(omega), B.imag] / w[:, None]  # (m, N+1)
        A = np.r_[A_re, A_im]
        b = np.r_[modulus.real / w, modulus.imag / w]
        sol, _ = nnls(A, b)
        G_inf = float(sol[0])
        G_i = sol[1:]
    else:
        A = np.r_[B.real / w[:, None], B.imag / w[:, None]]
        b = np.r_[(modulus.real - G_inf) / w, modulus.imag / w]
        G_i, _ = nnls(A, b)

    g_fit = G_inf + np.sum(G_i * B, axis=1)

    return {"G_inf": G_inf, "G_i": G_i, "tau_i": tau_i, "g_fit": g_fit}


def maxwell_to_prony(
    G_inf: float,
    G_i: NDArray,
    tau_i: NDArray,
) -> dict:
    """Normalize Maxwell weights into Prony fractions g_i = G_i / G_ins.

    G_ins (instantaneous shear modulus) = G_inf + sum(G_i). It is derivable
    from G_inf and g_i via G_ins = G_inf / (1 - sum(g_i)) and is therefore
    not stored separately.
    """
    G_ins = G_inf + float(np.sum(G_i))
    g_i = G_i / G_ins
    return {"g_i": g_i, "tau_i": tau_i, "G_inf": G_inf, "G_ins": G_ins}


def evaluate_prony_modulus(
    frequency_hz: NDArray,
    G_inf: float,
    G_i: NDArray,
    tau_i: NDArray,
) -> NDArray:
    """Evaluate the Maxwell/Prony series at arbitrary frequencies.

    Uses the absolute Maxwell weights G_i. To evaluate from a stored material
    file (which has g_i and G_inf), recover G_i = g_i * G_ins, where
    G_ins = G_inf / (1 - sum(g_i)).
    """
    omega = 2 * np.pi * np.asarray(frequency_hz)
    x = omega[:, None] * tau_i[None, :]
    B = (x ** 2 + 1j * x) / (1 + x ** 2)
    return G_inf + np.sum(G_i * B, axis=1)
