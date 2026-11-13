# Repository structure

All code is one installable Python package, `src/woodsites`, with one subpackage per module of
the system architecture. Modules only
talk to each other through files; the layouts of these files are in `docs/contracts/`.

```text
wood-industry-sites-detection/
├── src/woodsites/
│   ├── core/                 grid.py  config.py  polygons.py  sources.py     # shared by every module
│   ├── module1_reference/    model-independent: images and polygons
│   │   ├── imagery/          fetch_wms_chips.py  fetch_ni_cog_tiles.py  check_lgln_cog.py  check_lgln_stac.py
│   │   └── labelling/        fill_new_polygons_qgis.py                       # runs in the QGIS console
│   │                         (later: prefilter/)
│   ├── module2_detection/    model-specific: replaceable as a whole
│   │   └── dataset/          tile_and_chip.py  labels.py  raster.py  split.py  index.py  writers/
│   │                         (later: training/, prediction/)
│   └── module3_review/       (later: evaluation/, review/)
├── data/                     local data, never committed: reference/  detection/  review/
├── tests/                    synthetic data, no network, no QGIS
├── configs/                  config.example.toml (template); config.toml with real paths stays local
├── docs/                     structure, workflow, contracts/, decisions/
├── pyproject.toml · environment.yml
└── README.md · LICENSE · CHANGELOG.md · CONTRIBUTING.md
```

## Modules, their inputs and outputs

| Module | Task | Reads | Writes (in `data/`) |
|---|---|---|---|
| `module1_reference` | builds the reference set: fetches and freezes image tiles (`imagery`), people draw and check polygons in QGIS (`labelling`) | state WMS, LGLN COG | `data/reference/`: tiles + `manifest.csv`, polygon file with chip status, background list, holdout |
| `module2_detection` | turns the reference set into model inputs (`dataset`), later trains (`training`) and predicts (`prediction`) | `data/reference/` | `data/detection/`: datasets, model runs, `kandidaten_<lauf-id>.gpkg` |
| `module3_review` | holdout evaluation, model release, candidate review | candidates, holdout | `data/review/`: `freigabe.csv`, `pruefung.gpkg` (site register) |
| `core` | shared code: grid maths and IDs, config, readers for the reference files | – | – |

The boundary between Module 1 and Module 2: **Module 1 ends with the reference set** (GeoTIFF
archive + GeoPackage files). Everything model-specific – chips, label files, training,
prediction – is Module 2. The holdout belongs to Module 1 because it must be the same for
every model; the train/validation split belongs to Module 2 because it may change per run.

Rules:
- A module imports from `core`, never from another module. `core` imports from no module.
- Code moves into `core` only when a second module needs it.
- A top-level module exists where a defined product is handed over; parts inside a module
  (`imagery`, `labelling`, `dataset`, …) are created with their first file.
- Data never lives in git: `data/` is ignored except its README. The real locations are set in
  `configs/config.toml`; large or shared data (the image archive) may stay on a network drive.

## Running the scripts

From the repository folder, e.g.
`python src\woodsites\module2_detection\dataset\tile_and_chip.py check`. Each script finds the
package and `configs/config.toml` on its own. After `pip install -e .` the short commands
`woodsites-chips`, `woodsites-archive` and `woodsites-archive-ni` do the same. Details:
[`workflow.md`](workflow.md).
