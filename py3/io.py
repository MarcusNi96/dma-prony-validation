"""Shared IO helpers. Currently just metadata.json writer."""
import json
from datetime import datetime, timezone


def write_metadata(path, source_file, material, run, **extra):
    """Write a metadata.json with the standard baseline fields plus extras.

    Required: source_file, material, run, created_at (auto).
    Extras are merged in as-is.
    """
    meta = {
        "source_file": source_file,
        "material": material,
        "run": run,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    meta.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2) + "\n")
