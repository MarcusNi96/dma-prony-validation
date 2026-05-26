"""Plotting helpers — pure functions of arrays + a save path.

Conventions: log-log axes for moduli, semilog-x for tan(delta) and phase.
Save with dpi=150. Caller decides the path.
"""
import numpy as np
import matplotlib.pyplot as plt


def _evaluate_prony(freq_hz, G_inf, G_i, tau_i):
    """Maxwell/Prony series evaluated at given frequencies (Pa, complex)."""
    omega = 2 * np.pi * np.asarray(freq_hz)
    x = omega[:, None] * np.asarray(tau_i)[None, :]
    B = (x ** 2 + 1j * x) / (1 + x ** 2)
    return G_inf + np.sum(np.asarray(G_i) * B, axis=1)


def plot_master_curve_fit(freq, modulus_meas, fit, save_path, title=None):
    """Two panels: G' (loglog), G'' (loglog) in MPa.

    fit is a dict with keys (G_inf, G_i, tau_i).
    """
    f_min, f_max = float(freq.min()), float(freq.max())
    freq_dense = np.logspace(np.log10(f_min), np.log10(f_max), 400)
    G = _evaluate_prony(freq_dense, fit["G_inf"], fit["G_i"], fit["tau_i"])

    with plt.rc_context({
        "font.size": 16, "axes.titlesize": 18, "axes.labelsize": 16,
        "xtick.labelsize": 14, "ytick.labelsize": 14, "legend.fontsize": 14,
        "figure.titlesize": 20,
    }):
        fig, axes = plt.subplots(2, 1, figsize=(9, 9), sharex=True)

        axes[0].loglog(freq, modulus_meas.real / 1e6, "o", color="C0", markersize=5, label="Measured")
        axes[0].loglog(freq_dense, G.real / 1e6, "-", color="C1", linewidth=2, label="Prony fit")
        axes[0].set_ylabel("G' (MPa)")
        axes[0].set_title("Storage Modulus")
        axes[0].legend()
        axes[0].grid(True, which="both", alpha=0.3)

        axes[1].loglog(freq, modulus_meas.imag / 1e6, "o", color="C0", markersize=5, label="Measured")
        axes[1].loglog(freq_dense, G.imag / 1e6, "-", color="C1", linewidth=2, label="Prony fit")
        axes[1].set_xlabel("Frequency (Hz)")
        axes[1].set_ylabel("G'' (MPa)")
        axes[1].set_title("Loss Modulus")
        axes[1].legend()
        axes[1].grid(True, which="both", alpha=0.3)

        if title:
            fig.suptitle(title)
        plt.tight_layout()

        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
        plt.close(fig)


def plot_master_curve_diagnostic(
    freq_per_T, gp_per_T, gpp_per_T, temps_C,
    a_T, ref_temp,
    save_path=None, show=False, title=None, wlf=None,
):
    """Three panels: pre-shift data, master curve, shift factors.

    Per-temperature colors are preserved between the pre-shift and master
    panels so it's easy to see which T segment landed where. Filled markers
    are G'; open markers are G''. If `wlf=(C1, C2)` is given, the
    log10(a_T) panel also shows the smooth WLF curve.
    """
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    cmap = plt.get_cmap("viridis")
    span = max(1, max(temps_C) - min(temps_C))
    colors = [cmap((T - min(temps_C)) / span) for T in temps_C]

    for f, gp, gpp, T, c in zip(freq_per_T, gp_per_T, gpp_per_T, temps_C, colors):
        axes[0].loglog(f, gp, "o", color=c, markersize=4, label=f"{T:+.0f} °C")
        axes[0].loglog(f, gpp, "o", mfc="none", color=c, markersize=4)
    axes[0].set_xlabel("Frequency (Hz)")
    axes[0].set_ylabel("G', G'' (Pa)")
    axes[0].set_title("Pre-shift (filled = G', open = G'')")
    axes[0].grid(True, which="both", alpha=0.3)
    axes[0].legend(fontsize=7, ncol=2)

    for f, gp, gpp, c, a in zip(freq_per_T, gp_per_T, gpp_per_T, colors, a_T):
        axes[1].loglog(f * a, gp, "o", color=c, markersize=4)
        axes[1].loglog(f * a, gpp, "o", mfc="none", color=c, markersize=4)
    axes[1].set_xlabel(f"a_T · Frequency (Hz)   [T_ref = {ref_temp} °C]")
    axes[1].set_ylabel("G', G'' (Pa)")
    axes[1].set_title("Master curve")
    axes[1].grid(True, which="both", alpha=0.3)

    log10_aT = np.log10(np.asarray(a_T, dtype=float))
    axes[2].plot(temps_C, log10_aT, "o", color="C0", markersize=6, label="measured")
    if wlf is not None:
        C1, C2 = wlf
        T_smooth = np.linspace(min(temps_C), max(temps_C), 200)
        log10_aT_smooth = -C1 * (T_smooth - ref_temp) / (C2 + T_smooth - ref_temp)
        axes[2].plot(T_smooth, log10_aT_smooth, "-", color="C1",
                     label=f"WLF (C1={C1:.2f}, C2={C2:.1f})")
        axes[2].legend(fontsize=8)
    axes[2].axhline(0, color="k", lw=0.5, alpha=0.5)
    axes[2].axvline(ref_temp, color="k", lw=0.5, alpha=0.5)
    axes[2].set_xlabel("Temperature (°C)")
    axes[2].set_ylabel("log10(a_T)")
    axes[2].set_title("Shift factors")
    axes[2].grid(True, alpha=0.3)

    if title:
        fig.suptitle(title)
    plt.tight_layout()

    if save_path is not None:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150)
    if show:
        plt.show()
    plt.close(fig)


def plot_shaker_modulus(freq, modulus, save_path, title=None):
    """Diagnostic for a shaker run: G' (loglog) and tan(delta) (semilog-x).

    Used to eyeball the useful frequency band before adding the source to a
    Prony concat fit. `modulus` is the complex modulus from
    sources.load_shaker (already converted from accelerations).
    """
    fig, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True)

    axes[0].plot(freq, modulus.real, "o-", color="C0", markersize=3)
    axes[0].set_ylabel("G' (Pa)")
    axes[0].set_title("Storage Modulus")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(freq, modulus.imag / modulus.real, "o-",
                 color="C0", markersize=3)
    axes[1].set_xlabel("Frequency (Hz)")
    axes[1].set_ylabel("tan(δ)")
    axes[1].set_title("Loss Factor")
    axes[1].grid(True, alpha=0.3)

    if title:
        fig.suptitle(title)
    plt.tight_layout()

    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150)
    plt.close(fig)


def _frfs(f_hz, xdd, ydd, m):
    """Build complex accelerance / mobility / compliance from raw accel.

    xdd, ydd: complex base and mass accelerations (m/s^2). m: top-mass (kg).
    """
    w = 2 * np.pi * f_hz
    av = -1.0 / m * (ydd / xdd - 1.0)
    mv = av / (1j * w)
    cv = mv / (1j * w)
    return av, mv, cv


def plot_frf_grid(f_exp, xdd_exp, ydd_exp,
                  f_fea, xdd_fea, ydd_fea,
                  m, save_path, title=None):
    """3x4 grid: Accelerance / Mobility / Compliance rows;
    Magnitude / Real / Imag / Phase columns. Exp solid, FEA dashed."""
    av_e, mv_e, cv_e = _frfs(f_exp, xdd_exp, ydd_exp, m)
    av_f, mv_f, cv_f = _frfs(f_fea, xdd_fea, ydd_fea, m)

    rows = [
        ("Accelerance", (av_e, av_f), 1.0,  r"(m$\cdot$s$^{-2}$)/N"),
        ("Mobility",    (mv_e, mv_f), 1e3, r"(mm$\cdot$s$^{-1}$)/N"),
        ("Compliance",  (cv_e, cv_f), 1e6, r"$\mu$m/N"),
    ]
    cols = [
        ("Magnitude", lambda z: np.abs(z)),
        ("Real",      lambda z: z.real),
        ("Imag",      lambda z: z.imag),
        ("Phase",     lambda z: np.rad2deg(np.unwrap(np.angle(z)))),
    ]

    fig, axes = plt.subplots(3, 4, figsize=(16, 9), sharex=True)
    for i, (row_name, (y_e, y_f), scale, unit) in enumerate(rows):
        for j, (col_name, fn) in enumerate(cols):
            ax = axes[i, j]
            ax.plot(f_exp, fn(y_e * scale), color="C0", linestyle="-",
                    label="exp" if (i == 0 and j == 0) else None)
            ax.plot(f_fea, fn(y_f * scale), color="C0", linestyle="--",
                    label="fea" if (i == 0 and j == 0) else None)
            ax.grid(True, alpha=0.3)
            if i == 0:
                ax.set_title(col_name)
            if j == 0:
                ax.set_ylabel(f"{row_name} [{unit}]")
            if i == len(rows) - 1:
                ax.set_xlabel(r"$f$ (Hz)")
    axes[0, 0].legend()
    if title:
        fig.suptitle(title)
    plt.tight_layout()

    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150)
    plt.close(fig)


def plot_transmissibility(fea_curves, f_exp, T_exp, save_path, title=None):
    """Two panels: mass accel in G (top), unwrapped phase in deg (bottom).

    fea_curves: list of (f_fea, T_fea, label) tuples. One curve = single fit
    plot; multiple curves = comparison plot. Exp drawn solid; FEA curves
    dashed in distinct colors. Magnitudes are |T| · 1G — the mass response
    in G when the base is driven at 1G.
    """
    fig, axes = plt.subplots(2, 1, figsize=(10, 7))

    f_min = min([f_exp.min()] + [f.min() for f, _, _ in fea_curves])
    f_max = max([f_exp.max()] + [f.max() for f, _, _ in fea_curves])
    axes[0].plot([f_min, f_max], [1.0, 1.0], color="k", linestyle=":", linewidth=1,
                 label="Base Acceleration (1G)")
    axes[0].plot(f_exp, np.abs(T_exp), label="Mass Acceleration (Validation)", color="C0")
    for i, (f, T, lbl) in enumerate(fea_curves):
        axes[0].plot(f, np.abs(T), label=f"Mass Acceleration FEA: {lbl}",
                     color=f"C{i + 1}", linestyle="--")
    axes[0].set_xlabel("Frequency (Hz)")
    axes[0].set_ylabel("Acceleration (G)")
    axes[0].set_title("Mass Acceleration (1G base input)")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    phase_exp = np.rad2deg(np.unwrap(np.angle(T_exp)))
    axes[1].plot(f_exp, phase_exp, label="Validation", color="C0")
    for i, (f, T, lbl) in enumerate(fea_curves):
        phase = np.rad2deg(np.unwrap(np.angle(T)))
        axes[1].plot(f, phase, label=f"FEA: {lbl}", color=f"C{i + 1}", linestyle="--")
    axes[1].set_xlabel("Frequency (Hz)")
    axes[1].set_ylabel("phase(T) (deg)")
    axes[1].set_title("Phase (mass - base)")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    if title:
        fig.suptitle(title)
    plt.tight_layout()

    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
