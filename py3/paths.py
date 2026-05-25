"""Path conventions and config loaders.

Single source of truth for REPO_ROOT and where things live on disk.
Independent of cwd — REPO_ROOT comes from `__file__`.

Layout:
    config/<material>/base.json           handwritten material constants
    config/experiments/<name>.json        shaker test spec
    data/<material>/<src_type>/<run>.csv  processed measurement data
    results/<material>/...                everything the pipeline produces
"""
import json
import os
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------- config loading ----------

def load_json(rel_path):
    return json.loads((REPO_ROOT / rel_path).read_text())


def load_material(material):
    """Read config/<material>/base.json. If results/<material>/prony.json exists,
    merge it on top so callers get (nu, rho, G_inf, prony, ...) in one dict."""
    base = load_json(f"config/{material}/base.json")
    prony_path = REPO_ROOT / "results" / material / "prony.json"
    if prony_path.exists():
        merged = dict(base)
        merged.update(json.loads(prony_path.read_text()))
        return merged
    return base


def load_experiment(name):
    return load_json(f"config/experiments/{name}.json")


def abaqus_cmd():
    """ABAQUS_CMD env var > config.toml > Windows default."""
    env = os.environ.get("ABAQUS_CMD")
    if env:
        return env
    cfg_path = REPO_ROOT / "config.toml"
    if cfg_path.exists():
        with cfg_path.open("rb") as f:
            cfg = tomllib.load(f)
        cmd = cfg.get("abaqus", {}).get("cmd")
        if cmd:
            return cmd
    return r"C:\SIMULIA\Commands\abaqus.bat"


# ---------- canonical paths ----------

def processed_csv(material, source_type, run):
    """source_type is 'dma', 'shaker', or 'master'. `run` includes the .csv suffix
    if you want; otherwise we add it."""
    if not run.endswith(".csv"):
        run = f"{run}.csv"
    return REPO_ROOT / "data" / material / source_type / run


def config_base_path(material):
    return REPO_ROOT / "config" / material / "base.json"


def results_dir(material):
    return REPO_ROOT / "results" / material


def prony_path(material):
    return results_dir(material) / "prony.json"


def prony_fit_dir(material):
    return results_dir(material) / "prony_fit"


def master_dir(material):
    return results_dir(material) / "master"


def fea_results_dir(material, test, experiment):
    return results_dir(material) / "fea" / test / experiment


def fea_results_path(material, test, experiment):
    return fea_results_dir(material, test, experiment) / "results.json"


def fea_job_dir(material, test, experiment):
    """Abaqus working files."""
    return REPO_ROOT / "simulations" / f"{material}-{test}-{experiment}"
