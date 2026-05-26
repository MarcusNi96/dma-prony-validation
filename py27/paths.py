"""Py27 helpers for the Abaqus build script.

Uses os.path (not pathlib) to stay Py27-compatible. REPO_ROOT comes from
__file__ so it works from any cwd. Only REPO_ROOT and load_json are
needed — path composition (simulations/<m>/<exp>, results/<m>/...)
happens inline in the build script.
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
