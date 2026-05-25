# `data/raw/` — raw measurement data + the DMA processor

The contents of this folder (except this README and `process_dma.py`) are
**gitignored** — they hold large, machine-specific instrument files. Drop
your raw data here on each machine; nothing in here gets committed.

## Expected layout

```
data/raw/
├── README.md             (this file, tracked)
├── process_dma.py        (tracked)
├── <material>/           e.g. epdm_70, material_a   (untracked)
│   ├── dma/
│   │   ├── tf_015p/T150_TF.xls
│   │   ├── tf_015p/clean.json        (optional, see below)
│   │   ├── tf_015p_high/T150_TF.xls
│   │   └── ...
│   └── shaker/
│       ├── 1g_ds_33mm_6mm_573g/<live_sine>.csv
│       └── ...
```

One `.xls` per run sub-folder. Multiple `.xls` files in the same folder
will be rejected by the processor.

## Run-name conventions

| Prefix              | Meaning                                                       |
|---------------------|---------------------------------------------------------------|
| `f_<strain>p`       | Frequency sweep at `<strain>%` strain                         |
| `tf_<strain>p`      | Temperature-frequency sweep at `<strain>%` strain (low T)     |
| `tf_<strain>p_high` | Same, extended to high temperatures                            |
| `sd_<freq>hz`       | Strain dependence (amplitude sweep) at `<freq>` Hz             |
| `relaxation`        | Stress-relaxation test                                         |

## Running `process_dma.py`

Reads each `--run`'s raw `.xls`, applies its sibling `clean.json` if present,
applies the chamber→sample temperature compensation `T_s = 0.7·T_c + 7.5`
for any run whose name starts with `tf_`, concatenates the rows, and writes
**one CSV** (no metadata file) to `data/<material>/dma/<--out>`.

```bash
python data/raw/process_dma.py \
    --material epdm_70 \
    --run tf_015p tf_015p_high \
    --out tf_015p.csv
```

Result: `data/epdm_70/dma/tf_015p.csv` with columns

```
run, freq_hz, temperature_C,
G_storage_pa, G_loss_pa, G_abs_pa, tan_delta,
force_dyn_N, strain_dyn_pct
```

The leading `run` column records which raw run each row came from, so you
can split or filter after concatenation.

### Examples

Single run, no concat:

```bash
python data/raw/process_dma.py --material material_a --run f_025p --out f_025p.csv
```

Three runs combined:

```bash
python data/raw/process_dma.py \
    --material material_a \
    --run tf_015p tf_015p_high tf_025p \
    --out tf_all.csv
```

## `clean.json` (optional, per run)

Drop a `clean.json` next to a run's `.xls` to remove instrument artefacts
or bad cells before they reach the processed CSV. All fields optional.

```json
{
  "exclude_freq_hz": [50, 100],
  "tolerance_hz": 0.001,
  "exclude_temperature_C": [25],
  "tolerance_C": 1.0,
  "exclude_points": [
    {"temperature_C": -25, "freq_hz": 100, "reason": "mains hum"}
  ]
}
```

- `exclude_freq_hz` — drop these frequencies across every isotherm.
- `exclude_temperature_C` — drop entire isotherms (e.g. a duplicate 25 °C overlap).
- `exclude_points` — drop individual `(T, f)` cells.
- `tolerance_hz` / `tolerance_C` — matching tolerance (defaults shown).

## Notes

- `data/<material>/dma/*.csv` is the contract input for the rest of the
  pipeline (master-curve build, Prony fit, FEA). Those scripts never read
  `data/raw/`.
- The temperature compensation only fires for `tf_*` runs because for those
  the rubber sample lags the chamber air; the relation
  `T_s = 0.7·T_c + 7.5` was calibrated empirically.
- The 25 °C chamber set-point happens to map to 25 °C sample, so anchoring
  master curves at `T_ref = 25 °C` survives the compensation unchanged.
