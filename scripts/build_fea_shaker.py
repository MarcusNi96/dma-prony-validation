"""Abaqus FEA build for the 3D shaker test (Python 2.7, runs in Abaqus).

Run via:
    abaqus cae noGUI=scripts/build_fea_shaker.py -- \
        --material <m> --config <name>

Loads two JSON files (see main() - flat, explicit):
    results/<material>/abaqus_input.json  base{nu, rho, G_inf} + prony{...} + wlf{...}
    config/shaker/<config>.json           mass_kg, mass_width, thickness/diameters,
                                          f_min, f_max, base_accel, ...

Writes:
    simulations/<material>/<config>/                       Abaqus job working dir
    results/<material>/validation/<config>/result.json     history output (post-run)
"""
import argparse
import math
import os
import sys

from abaqus import *
from abaqusConstants import *
from caeModules import *
import odbAccess



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

from py27.paths import REPO_ROOT, load_json
from py27.history_access import HistoryAccess, export


# ---------- argparse ----------

def parse_args():
    # Abaqus 2022 passes its own CLI flags (-cae, -noGUI, -lmlog, -tmpdir ...)
    # in sys.argv and may swallow the `--` separator. Use parse_known_args so
    # argparse only consumes our long flags and ignores Abaqus's args.
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--material", required=True)
    p.add_argument("--config", required=True,
                   help="config name, e.g. 1g_258g (matches config/shaker/<config>.json)")
    args, _unknown = p.parse_known_args(argv)
    return args


# ---------- FEA knobs ----------

N_FREQ = 20           # SteadyStateDirect points across the measured range
SEED_SIZE = 0.003     # m, mesh seed (unused at the moment, kept for future use)


# ---------- glue ----------

def main():
    args = parse_args()

    # Two explicit JSON reads. Each value below comes from exactly one file.
    material     = load_json("results/%s/abaqus_input.json" % args.material)
    config       = load_json("config/shaker/%s.json" % args.config)

    # chdir to the job dir so Abaqus writes .cae/.odb/.log there
    job_dir = os.path.join(REPO_ROOT, "simulations", args.material, args.config)
    if not os.path.exists(job_dir):
        os.makedirs(job_dir)
    os.chdir(job_dir)

    ### Sketch and Part
    OUTER_D = config["outer_diameter_m"]
    INNER_D = config["inner_diameter_m"]
    THICKNESS = config["thickness_m"]

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
    NAME = args.material
    NU = material["base"]["nu"]
    RHO = material["base"]["rho"]
    G_INF = material["prony"]["G_inf"]
    g_I = material["prony"]["g_i"]
    TAU_I = material["prony"]["tau_i"]

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

    GAP = config["mass_width"]
    MASS_KG = config["mass_kg"]
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

    F_MIN  = config["f_min"]
    F_MAX  = config["f_max"]
    BASE_A = config["base_accel"]   # m/s^2

    m.SteadyStateDirectStep(
        name="Frequency", previous="Initial",
        frequencyRange=((F_MIN, F_MAX, N_FREQ, 1.0),),
        scale=LINEAR,
    )

    # Drive constant-amplitude base acceleration BASE_A by setting the
    # corresponding displacement amplitude u(f) = -BASE_A / (2*pi*f)^2.
    freqs = [F_MIN + i * (F_MAX - F_MIN) / (N_FREQ - 1) for i in range(N_FREQ)]
    amp_data = tuple((f, -BASE_A / (2 * math.pi * f) ** 2) for f in freqs)
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
    job_name = "%s-%s" % (args.material, args.config)
    mdb.Job(name=job_name, model="Model-1")
    mdb.jobs[job_name].submit(consistencyChecking=OFF)
    mdb.jobs[job_name].waitForCompletion()

    cae_path = job_name + ".cae"
    mdb.saveAs(pathName=cae_path)
    print("Saved CAE: %s" % os.path.abspath(cae_path))

    # ---- extract MassRP A2 from ODB -> result.json ----
    results_dir = os.path.join(REPO_ROOT, "results", args.material,
                               "validation", args.config)
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)
    results_path = os.path.join(results_dir, "result.json")
    odb = odbAccess.openOdb(job_name + ".odb")
    results = HistoryAccess(odb).region("MassRP").name("A2").fetch()
    export(results, results_path)
    odb.close()
    print("Saved results: %s" % results_path)


if __name__ == "__main__":
    main()
