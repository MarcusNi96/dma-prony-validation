"""Shared dispatch for matrix-driven drivers (run_fits.py, run_matrix.py).

Each entry in a matrix JSON file is one of:

    {"name": str, "workflow": <key>,          "args": <dict>}                  # named workflow
    {"name": str, "script":   "<rel/path>",   "args": <dict>, "runner"?: ..}   # one script
    {"name": str, "scripts":  [<step>, ...],                  "runner"?: ..}   # ordered steps

In the third form each <step> is either:
    "scripts/foo.py"                                            # uses entry-level runner+args
    {"path": "scripts/foo.py", "runner"?: ..., "args"?: <dict>} # per-step overrides

`workflow` keys are looked up in the `scripts` mapping passed in by the
caller. `script` / `scripts` skip that lookup - the path is taken as-is,
relative to repo root.

`runner` controls invocation (default: "python"):
    "python"  -> [sys.executable, script, ...args]
    "abaqus"  -> [abaqus_cmd, "cae", "noGUI=script", "--", ...args]

`args` keys are translated to CLI flags by replacing `_` with `-` and
prefixing `--`. List values become repeated flags (`--source A --source B`).
True booleans become bare flags; False/None values are dropped.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from py3.paths import REPO_ROOT, abaqus_cmd


def args_to_cli(args):
    """dict -> list of CLI arg tokens."""
    out = []
    for k, v in args.items():
        flag = f"--{k.replace('_', '-')}"
        if v is None:
            continue
        if isinstance(v, bool):
            if v:
                out.append(flag)
            continue
        if isinstance(v, list):
            for x in v:
                out.extend([flag, str(x)])
        else:
            out.extend([flag, str(v)])
    return out


def _build_cmd(script_path, args, runner):
    cli_args = args_to_cli(args)
    if runner == "abaqus":
        return [abaqus_cmd(), "cae", f"noGUI={script_path}", "--"] + cli_args
    if runner == "python":
        return [sys.executable, script_path] + cli_args
    raise SystemExit(f"unknown runner {runner!r}; expected 'python' or 'abaqus'")


def _run_path(script_path, args, label, keep_going, runner):
    cmd = _build_cmd(script_path, args, runner)
    print(f"\n--- {label} ---")
    print("$", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        msg = f"{label} failed (exit {proc.returncode})"
        if keep_going:
            print("!!", msg, "; continuing (--keep-going)")
        else:
            raise SystemExit(msg + "; pass --keep-going to continue past failures")


def _run_entry(scripts, composites, entry, keep_going):
    name = entry["name"]
    args = entry.get("args", {})
    runner = entry.get("runner", "python")

    # Direct script path(s) - skip workflow lookup
    if "script" in entry:
        _run_path(entry["script"], args, name, keep_going, runner)
        return
    if "scripts" in entry:
        for step in entry["scripts"]:
            if isinstance(step, str):
                path, step_runner, step_args = step, runner, args
            else:
                path = step["path"]
                step_runner = step.get("runner", runner)
                step_args = step.get("args", args)
            _run_path(path, step_args, f"{name}: {path}", keep_going, step_runner)
        return

    # Named workflow - look up in caller's scripts mapping
    workflow = entry["workflow"]
    if workflow in composites:
        for sub in composites[workflow]:
            if sub not in scripts:
                raise SystemExit(f"unknown workflow {sub!r}")
            _run_path(scripts[sub], args, f"{name}: {sub}", keep_going, runner)
    else:
        if workflow not in scripts:
            raise SystemExit(f"unknown workflow {workflow!r}")
        _run_path(scripts[workflow], args, name, keep_going, runner)


def main(default_matrix, scripts, composites=None, description=None):
    """Parse argv, load the matrix, and run the selected entries.

    `default_matrix` is the Path used when --matrix is not given.
    `scripts` maps workflow name -> script path (relative to repo root).
    `composites` maps workflow name -> ordered tuple of sub-workflow names.
    """
    composites = composites or {}
    p = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--matrix", default=None,
                   help=f"Path to matrix JSON (default: {default_matrix.name})")
    p.add_argument("--only", nargs="+", default=None,
                   help="Names of entries to run; default = all entries.")
    p.add_argument("--keep-going", action="store_true",
                   help="Continue running entries after one fails.")
    args = p.parse_args()

    matrix_path = Path(args.matrix) if args.matrix else default_matrix
    matrix = json.loads(matrix_path.read_text())

    if args.only:
        selected = [e for e in matrix if e["name"] in args.only]
        missing = set(args.only) - {e["name"] for e in selected}
        if missing:
            raise SystemExit(f"no entries matched names: {sorted(missing)}")
    else:
        selected = matrix

    print(f"Running {len(selected)} of {len(matrix)} entries from {matrix_path.name}")
    for entry in selected:
        _run_entry(scripts, composites, entry, args.keep_going)
    print(f"\nAll {len(selected)} entries completed.")
