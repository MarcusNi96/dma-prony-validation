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
import csv
import math
import os
import sys

from abaqus import *
from abaqusConstants import *
from caeModules import *
import odbAccess

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
from py27.history_access import HistoryAccess, export


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

def shaker_freq_range(csv_path):
    """Return (f_min_hz, f_max_hz) from the measured shaker CSV."""
    freqs = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            freqs.append(float(row["freq_hz"]))
    if not freqs:
        raise RuntimeError("no rows in %s" % csv_path)
    return min(freqs), max(freqs)


def load_all_configs(material, experiment, shaker_run):
    """Pull everything off disk in one place. Returns a dict; downstream code
    reads from it explicitly so it's obvious what each Abaqus call depends on."""
    mat = load_material(material)             # base.json + prony.json merged
    exp = load_experiment(experiment)
    if shaker_run is None:
        shaker_run = experiment[len("shaker_"):] if experiment.startswith("shaker_") else experiment
    shaker_csv = processed_csv(material, "Model-1", shaker_run)
    f_min_hz, f_max_hz = shaker_freq_range(shaker_csv)

    cfg = {
        "material":   material,
        "experiment": experiment,
        "test_name":  TEST_NAME,
        "model_name": "Shaker",
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
        "mass_width":       float(exp["mass_width"]),
        "thickness_m":      float(exp["thickness_m"]),
        "outer_diameter_m": float(exp["outer_diameter_m"]),
        "inner_diameter_m": float(exp["inner_diameter_m"]),
        # frequency range derived from the measured shaker CSV
        "f_min":            f_min_hz,
        "f_max":            f_max_hz,
        "n_freq":           N_FREQ,
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
    print("experiment      : mass=%g kg, mass_width=%g m, t=%g m, OD=%g m, ID=%g m"
          % (cfg["mass_kg"], cfg["mass_width"], cfg["thickness_m"],
             cfg["outer_diameter_m"], cfg["inner_diameter_m"]))
    print("freq range      : %.2f .. %.2f Hz (%d pts, from shaker CSV)"
          % (cfg["f_min"], cfg["f_max"], cfg["n_freq"]))
    print("shaker csv      : %s" % os.path.relpath(cfg["shaker_csv"], REPO_ROOT))
    print("job dir         : %s" % os.path.relpath(cfg["job_dir"], REPO_ROOT))
    print("=" * 60)


# ---------- Abaqus build (your math goes here) ----------

def build_model(cfg):

    OUTER_D = cfg["outer_diameter_m"]
    INNER_D = cfg["inner_diameter_m"]
    THICKNESS = cfg["thickness_m"]

    m = mdb.models["Model-1"]
    s = m.ConstrainedSketch(name="__profile__", sheetSize=0.1)
    s.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, OUTER_D/2))
    s.CircleByCenterPerimeter(center=(0.0, 0.0), point1=(0.0, INNER_D/2))

    p = m.Part(name="Disk", dimensionality=THREE_D, type=DEFORMABLE_BODY)
    p.BaseSolidExtrude(sketch=s, depth=THICKNESS)

    dp1 = p.DatumPlaneByPrincipalPlane(principalPlane=XZPLANE, offset=0.0)
    dp2 = p.DatumPlaneByPrincipalPlane(principalPlane=YZPLANE, offset=0.0)
    p.PartitionCellByDatumPlane(datumPlane=p.datums[dp1.id], cells=p.cells[:])
    p.PartitionCellByDatumPlane(datumPlane=p.datums[dp2.id], cells=p.cells[:])

    eps = 1e-4
    p.Set(
        faces=p.faces.getByBoundingBox(
            xMin=-OUTER_D - eps, yMin=-OUTER_D - eps, zMin=-eps,
            xMax=OUTER_D + eps, yMax=OUTER_D+ eps, zMax=eps,
        ),
        name="BaseFace",
    )
    p.Set(
        faces=p.faces.getByBoundingBox(
            xMin=-OUTER_D - eps, yMin=-OUTER_D- eps, zMin=THICKNESS- eps,
            xMax=OUTER_D + eps, yMax=OUTER_D + eps, zMax=THICKNESS + eps,
        ),
        name="LoadFace",
    )

    ### The following Edge selection is written by Claude Code
    inner_r = INNER_D / 2.0
    outer_r = OUTER_D / 2.0
    z_mid = THICKNESS / 2.0
    r_mid = (inner_r + outer_r) / 2.0
    s2 = 1.0 / math.sqrt(2.0)
    quadrant_signs = [(1, 1), (-1, 1), (-1, -1), (1, -1)]

    # Axial: at outer/inner radius on x or y axis, midpoint in z
    axial_pts = [
        (r * sx, r * sy, z_mid)
        for r in (inner_r, outer_r)
        for sx, sy in [(1, 0), (-1, 0), (0, 1), (0, -1)]
    ]

    # Radial: midpoint between inner/outer radius, on x or y axis, at z=0 and z=THICKNESS
    radial_pts = [
        (r_mid * sx, r_mid * sy, z)
        for z in (0.0, THICKNESS)
        for sx, sy in [(1, 0), (-1, 0), (0, 1), (0, -1)]
    ]

    # Tangential: arcs at 45 per quadrant, on each radius, at z=0 and z=THICKNESS
    tangential_pts = [
        (r * s2 * sx, r * s2 * sy, z)
        for z in (0.0, THICKNESS)
        for r in (inner_r, outer_r)
        for sx, sy in quadrant_signs
    ]

    p.Set(name="AxialEdges",      edges=p.edges.findAt(*[(pt,) for pt in axial_pts]))
    p.Set(name="RadialEdges",     edges=p.edges.findAt(*[(pt,) for pt in radial_pts]))
    p.Set(name="TangentialEdges", edges=p.edges.findAt(*[(pt,) for pt in tangential_pts]))

    # --- material + section ---
    NAME = cfg["material"]
    NU = cfg["nu"]
    RHO = cfg["rho"]
    G_INF = cfg["G_inf"]
    g_I = cfg["g_i"]
    TAU_I = cfg["tau_i"]

    E_INF = G_INF*2*(1+NU)


    m.Material(name=NAME)
    m.materials[NAME].Elastic(table=((E_INF, NU),), moduli = LONG_TERM)
    m.materials[NAME].Density(table=((RHO,),))
    m.materials[NAME].Viscoelastic(
        domain=FREQUENCY, frequency=PRONY,
        table=tuple((g, 0.0, t) for g, t in zip(g_I, TAU_I)),
    )
    m.HomogeneousSolidSection(name="Rubber-Sec", material=NAME, thickness=None)
    p.Set(cells=p.cells[:], name="All")
    p.SectionAssignment(
        region=p.sets["All"], sectionName="Rubber-Sec", offset=0.0,
        offsetType=MIDDLE_SURFACE, offsetField="", thicknessAssignment=FROM_SECTION,
    )

        # --- assembly ---

    GAP = cfg["mass_width"]
    MASS_KG = cfg["mass_kg"]
    a = m.rootAssembly
    a.Instance(name="Left-disk", part=p, dependent=ON)
    a.rotate(
        instanceList=("Left-disk",), axisPoint=(0.0, 0.0, 0.0),
        axisDirection=(0.0, 1.0, 0.0), angle=90.0,
    )
    a.Instance(name="Right-disk", part=p, dependent=ON)
    a.rotate(
        instanceList=("Right-disk",), axisPoint=(0.0, 0.0, 0.0),
        axisDirection=(0.0, 1.0, 0.0), angle=-90.0,
    )

    a.translate(instanceList=("Right-disk",), vector=(GAP+THICKNESS, 0.0, 0.0) )



    a.ReferencePoint(point=(GAP/2 + THICKNESS, 0.0 , 0.0))
    rp_key = a.referencePoints.keys()[-1]
    a.Set(name="MassRP", referencePoints=(a.referencePoints[rp_key],))

    a.engineeringFeatures.PointMassInertia(
        name="MassInertia", region=a.sets["MassRP"], mass=MASS_KG,
        )

    faces_right = a.instances["Right-disk"].sets["LoadFace"].faces
    faces_left = a.instances["Left-disk"].sets["LoadFace"].faces
    a.Set(name="LoadFaces", faces=faces_right + faces_left)
    m.Coupling(
        name="MassCoupling", controlPoint=a.sets["MassRP"], surface=a.sets["LoadFaces"],
        influenceRadius=WHOLE_SURFACE, couplingType=KINEMATIC, localCsys=None,
        u1=ON, u2=ON, u3=ON, ur1=ON, ur2=ON, ur3=ON,
    )

    faces_right = a.instances["Right-disk"].sets["BaseFace"].faces
    faces_left  = a.instances["Left-disk"].sets["BaseFace"].faces
    a.Set(name="BaseFaces", faces=faces_right + faces_left)

    # --- mesh ---
    p.seedEdgeByBias(biasMethod=DOUBLE, endEdges=p.sets["RadialEdges"].edges,
                     ratio=5.0, number=10, constraint=FINER)
    p.seedEdgeByNumber(edges=p.sets["TangentialEdges"].edges, number=5, constraint=FINER)
    p.seedEdgeByNumber(edges=p.sets["AxialEdges"].edges, number=10, constraint=FINER)
    p.setMeshControls(regions=p.cells[:], elemShape=HEX, technique=STRUCTURED)
    p.setElementType(
        regions=(p.sets["All"].cells,),
        elemTypes=(
            mesh.ElemType(elemCode=C3D8H, elemLibrary=STANDARD),
            mesh.ElemType(elemCode=C3D6, elemLibrary=STANDARD),
        ),
    )
    p.generateMesh()

    F_MIN  = cfg["f_min"]
    F_MAX  = cfg["f_max"]
    N_FREQ = 20

    m.SteadyStateDirectStep(
        name="Frequency", previous="Initial",
        frequencyRange=((F_MIN, F_MAX, N_FREQ, 1.0),),
        scale=LINEAR,
    )

    freqs = [F_MIN + i * (F_MAX - F_MIN) / (N_FREQ - 1) for i in range(N_FREQ)]
    amp_data = tuple((f, 9.81 / -(2 * math.pi * f) ** 2) for f in freqs)
    print("amp_data:")
    for f, u in amp_data:
        print("  %.4f Hz -> %.6e" % (f, u))

    m.TabularAmplitude(name="One", timeSpan=STEP, smooth=SOLVER_DEFAULT, data=amp_data)

    m.DisplacementBC(
        name="BC-Base", createStepName="Initial",
        region=a.sets["BaseFaces"],
        u1=SET, u2=SET, u3=SET
    )
    m.boundaryConditions["BC-Base"].setValuesInStep(
        stepName="Frequency",
        u2=1.0+0j,
        amplitude="One",
    )
    m.HistoryOutputRequest(
        name="H-accel-mass", createStepName="Frequency",
        variables=("A2",), region=a.allSets["MassRP"],
    )
    m.HistoryOutputRequest(
        name="H-accel-base", createStepName="Frequency",
        variables=("A2",), region=a.allSets["BaseFaces"],
    )

    # ---- submit job ----
    job_name = "%s-%s" % (cfg["material"], cfg["experiment"])
    mdb.Job(name=job_name, model=cfg["model_name"])
    mdb.jobs[job_name].submit(consistencyChecking=OFF)
    mdb.jobs[job_name].waitForCompletion()

    cae_path = job_name + ".cae"
    mdb.saveAs(pathName=cae_path)
    print("Saved CAE: %s" % os.path.abspath(cae_path))

    # ---- extract MassRP A2 from ODB -> results.json ----
    results_path = cfg["results_json"]
    results_dir = os.path.dirname(results_path)
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)
    odb = odbAccess.openOdb(job_name + ".odb")
    results = HistoryAccess(odb).region("MassRP").name("A2").fetch()
    export(results, results_path)
    odb.close()
    print("Saved results: %s" % results_path)
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
