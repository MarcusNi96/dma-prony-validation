"""Path conventions and config loaders.

Single source of truth for REPO_ROOT and where things live on disk.
Independent of cwd — REPO_ROOT comes from `__file__`.

Layout:
    config/<material>/base.json           handwritten material constants
    config/shaker/<name>.json             shaker test spec
    data/<material>/<src_type>/<run>.csv  processed measurement data
    results/<material>/...                everything the pipeline produces
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_json(rel_path):
    return json.loads((REPO_ROOT / rel_path).read_text())


def processed_csv(material, source_type, run):
    """source_type is 'dma', 'shaker', or 'master'. `run` includes the .csv suffix
    if you want; otherwise we add it."""
    if not run.endswith(".csv"):
        run = f"{run}.csv"
    return REPO_ROOT / "data" / material / source_type / run


def master_dir(material):
    return REPO_ROOT / "results" / material / "master"


def prony_fit_dir(material):
    return REPO_ROOT / "results" / material / "prony_fit"


def abaqus_input_path(material):
    return REPO_ROOT / "results" / material / "abaqus_input.json"
