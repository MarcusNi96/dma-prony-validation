# dma-prony-validation

Fit a Prony series for a viscoelastic material from DMA measurements, then
validate it by FEA against shaker measurements.

## Layout

```
config/<material>/base.json        constants: nu, rho, G_inf
config/experiments/<name>.json     shaker test specs (mass, geometry, ...)

data/raw/                          gitignored — raw .xls / .csv lives here
data/raw/process_dma.py            DMA processor (see data/raw/README.md)
data/<material>/dma/<run>.csv      processed DMA, the contract input
data/<material>/shaker/<run>.csv   processed shaker, contract input

core/    science modules (mechanics, tts, plots)
py3/     boilerplate (paths, sources, io, matrix_runner)
py27/    Abaqus harness (Python 2.7 — required by Abaqus)

scripts/                           CLI entry points (one script per concern)
results/<material>/                gitignored — fit + FEA outputs
```

## End-to-end workflow

1. **Process DMA** — see [data/raw/README.md](data/raw/README.md).
   Writes `data/<material>/dma/<run>.csv`.
2. **Process shaker** — `python scripts/process_shaker.py …`
   Writes `data/<material>/shaker/<run>.csv`.
3. **Build master curve** — `python scripts/build_master_curve.py --material <m> --run <run>`
   Writes `results/<material>/master/master_curve.csv` + diagnostic plot.
4. **Fit Prony** — `python scripts/fit_prony.py --material <m>`
   Writes `results/<material>/prony.json` + `results/<material>/prony_fit/fit.png`.
5. **Build FEA** — `python scripts/build_fea_shaker.py --material <m> --experiment <name>`
   Runs the Abaqus job. Output under `simulations/`.
6. **Plot FEA vs measured** — `python scripts/plot_fea.py --material <m> --experiment <name>`
   Writes transmissibility + FRF plots under `results/<m>/fea/<test>/<exp>/`.

## Naming conventions

- **Material**: lowercase, no spaces. `epdm_70`, `material_a`.
- **DMA runs**: prefix-coded — `f_*`, `tf_*`, `sd_*`, `relaxation` (see [data/raw/README.md](data/raw/README.md)).
- **Shaker experiments**: `shaker_<accel>_ds_<OD>mm_<t>mm_<mass>g` (e.g. `shaker_1g_ds_33mm_6mm_573g`).

## Design notes

- **One fit per material.** No `master` / `concat` split. If you need to A/B test a
  different fit, branch the repo.
- **`data/<material>/...` is a contract.** Once a column is published, downstream
  scripts depend on it. Add columns freely; renaming or removing breaks the world.
- **`results/` is disposable.** Everything in it is regenerable from `data/` +
  `config/`. Wipe and rerun the pipeline as a smoke test before any handoff.
- **Notebooks live in `notebooks/`.** Once a notebook cell is settled, move it to a
  script — don't leave logic in notebooks long-term.

## Python

`requires-python = ">=3.11,<3.14"`. 3.14 + ipykernel 7 hangs in VS Code
Jupyter (microsoft/vscode-jupyter#17228); stay on 3.13 or earlier.
