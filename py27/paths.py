"""Py27 mirror of py3/paths.py for Abaqus scripts.

Uses os.path (not pathlib) to stay Py27-compatible. REPO_ROOT comes from
__file__ so it works from any cwd.

Layout (must match py3/paths.py):
    config/<material>/base.json           nu, rho, G_inf
    config/shaker/<name>.json             shaker test spec
    data/<material>/<src_type>/<run>.csv  processed measurement data
    results/<material>/prony.json         Prony fit + (optionally) WLF
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _to_bytes(obj):
    """Recursively coerce unicode -> bytes (Abaqus 2022's Py27 chokes on unicode in some Region calls)."""
    if sys.version_info[0] >= 3:
        return obj
    if isinstance(obj, unicode):  # noqa: F821 - Py27 only
        return obj.encode("utf-8")
    if isinstance(obj, list):
        return [_to_bytes(item) for item in obj]
    if isinstance(obj, dict):
        return dict((_to_bytes(k), _to_bytes(v)) for k, v in obj.iteritems())
    return obj


def load_json(rel_path):
    with open(os.path.join(REPO_ROOT, rel_path), "r") as f:
        return _to_bytes(json.load(f))


def load_material(material):
    """Read config/<m>/base.json. If results/<m>/prony.json exists, merge it
    on top so callers get (nu, rho, G_inf, prony, [wlf], ...) in one dict."""
    base = load_json("config/%s/base.json" % material)
    prony_rel = "results/%s/prony.json" % material
    if os.path.exists(os.path.join(REPO_ROOT, prony_rel)):
        prony = load_json(prony_rel)
        merged = dict(base)
        merged.update(prony)
        return merged
    return base


def load_experiment(name):
    return load_json("config/shaker/%s.json" % name)


def processed_csv(material, source_type, run):
    """source_type is 'dma', 'shaker', or 'master'."""
    if not run.endswith(".csv"):
        run = run + ".csv"
    return os.path.join(REPO_ROOT, "data", material, source_type, run)


def fea_job_dir(material, experiment):
    return os.path.join(REPO_ROOT, "simulations",
                        "%s-%s" % (material, experiment))


def fea_results_path(material, experiment):
    return os.path.join(REPO_ROOT, "results", material,
                        "validation", experiment, "result.json")
