"""Abaqus FEA build for the 3D linear shaker test (Python 2.7, runs in Abaqus).

Run via:
    abaqus cae noGUI=scripts/build_fea_shaker.py -- \
        --material <m> --experiment <name> [--shaker-run <run>]

Loads:
    config/<material>/base.json          nu, rho
    results/<material>/prony.json        G_inf, prony{g_i, tau_i}, wlf{C1, C2, T_ref_C}
    config/experiments/<exp>.json        mass_kg, geometry, ...
    data/<material>/shaker/<run>.csv     measured base accel for TabularAmplitude
                                         (defaults to --experiment with the
                                         'shaker_' prefix stripped)

Writes:
    simulations/<material>-<test>-<exp>/                  Abaqus job working dir
    results/<material>/fea/<test>/<exp>/results.json      history output (post-run)
"""
import argparse
import math
import os
import sys


# ---- FEA knobs (tweak here) ----
TEST_NAME = "3d_linear_shaker"
SEED_SIZE = 0.003     # m, mesh seed
N_FREQ = 50           # SteadyStateDirect points across the measured range


def _find_repo_root():
    """abaqus cae noGUI=script.py doesn't set __file__ reliably; walk up for py27/."""
    try:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    p = os.path.abspath(os.getcwd())
    while not os.path.isdir(os.path.join(p, "py27")):
        parent = os.path.dirname(p)
        if parent == p:
            raise RuntimeError("Cannot locate repo root (no py27/ in cwd or above)")
        p = parent
    return p


sys.path.insert(0, _find_repo_root())

from py27.paths import (
    REPO_ROOT, fea_job_dir, fea_results_path,
    load_experiment, load_material, processed_csv,
)


# ---------- argparse ----------

def parse_args():
    # Abaqus passes everything after `--` to the script; argparse handles that
    # the same as a normal CLI.
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--material", required=True)
    p.add_argument("--experiment", required=True,
                   help="experiment name, e.g. shaker_1g_ds_33mm_6mm_573g")
    p.add_argument("--shaker-run", default=None,
                   help="processed shaker CSV stem under data/<material>/shaker/. "
                        "Default: --experiment with leading 'shaker_' stripped.")
    return p.parse_args()


# ---------- config loaders (boring) ----------

def load_all_configs(material, experiment, shaker_run):
    """Pull everything off disk in one place. Returns a dict; downstream code
    reads from it explicitly so it's obvious what each Abaqus call depends on."""
    mat = load_material(material)             # base.json + prony.json merged
    exp = load_experiment(experiment)
    if shaker_run is None:
        shaker_run = experiment[len("shaker_"):] if experiment.startswith("shaker_") else experiment
    shaker_csv = processed_csv(material, "shaker", shaker_run)

    cfg = {
        # material constants
        "nu":      float(mat["nu"]),
        "rho":     float(mat["rho"]),
        "G_inf":   float(mat["G_inf"]),
        # derived: long-term Young's for the FEA *Elastic card
        "E_inf":   2.0 * (1.0 + float(mat["nu"])) * float(mat["G_inf"]),
        # Prony series
        "g_i":     [float(g) for g in mat["prony"]["g_i"]],
        "tau_i":   [float(t) for t in mat["prony"]["tau_i"]],
        # WLF (optional — Abaqus *VISCOELASTIC card needs all three)
        "wlf":     mat.get("wlf"),
        # experiment geometry / mass
        "mass_kg":          float(exp["mass_kg"]),
        "thickness_m":      float(exp["thickness_m"]),
        "outer_diameter_m": float(exp["outer_diameter_m"]),
        "inner_diameter_m": float(exp["inner_diameter_m"]),
        # other experiment fields passed through as-is for the model builder
        "experiment_raw":   exp,
        # IO paths
        "shaker_csv":  shaker_csv,
        "job_dir":     fea_job_dir(material, TEST_NAME, experiment),
        "results_json": fea_results_path(material, TEST_NAME, experiment),
    }
    return cfg


def summarize(cfg):
    print("=" * 60)
    print("material        : nu=%g, rho=%g, G_inf=%.3e Pa, E_inf=%.3e Pa"
          % (cfg["nu"], cfg["rho"], cfg["G_inf"], cfg["E_inf"]))
    print("prony           : %d terms (tau range %.2e .. %.2e s)"
          % (len(cfg["g_i"]),
             min(cfg["tau_i"]) if cfg["tau_i"] else float("nan"),
             max(cfg["tau_i"]) if cfg["tau_i"] else float("nan")))
    if cfg["wlf"]:
        print("wlf             : C1=%.3f, C2=%.3f K, T_ref=%.1f C"
              % (cfg["wlf"]["C1"], cfg["wlf"]["C2"], cfg["wlf"]["T_ref_C"]))
    else:
        print("wlf             : (none in prony.json)")
    print("experiment      : mass=%g kg, t=%g m, OD=%g m, ID=%g m"
          % (cfg["mass_kg"], cfg["thickness_m"],
             cfg["outer_diameter_m"], cfg["inner_diameter_m"]))
    print("shaker csv      : %s" % os.path.relpath(cfg["shaker_csv"], REPO_ROOT))
    print("job dir         : %s" % os.path.relpath(cfg["job_dir"], REPO_ROOT))
    print("=" * 60)


# ---------- Abaqus build (your math goes here) ----------

def build_model(cfg):
    """TODO: build geometry, material (*Elastic + *Viscoelastic prony + WLF),
    mesh, assembly, step (SteadyStateDirect or Modal), BCs (base TabularAmplitude
    from cfg['shaker_csv']), kinematic coupling to mass RP, run job, export
    history to cfg['results_json']."""
    raise NotImplementedError("FEA build not implemented yet")


# ---------- glue ----------

def main():
    args = parse_args()
    cfg = load_all_configs(args.material, args.experiment, args.shaker_run)
    summarize(cfg)

    # Ensure job dir exists; chdir so Abaqus writes its files there
    if not os.path.exists(cfg["job_dir"]):
        os.makedirs(cfg["job_dir"])
    cwd_before = os.getcwd()
    os.chdir(cfg["job_dir"])
    try:
        build_model(cfg)
    finally:
        os.chdir(cwd_before)


if __name__ == "__main__":
    main()
