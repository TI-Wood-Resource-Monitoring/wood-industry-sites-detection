# Wood Industry Sites Detection

Detection of wood industry sites and logyards in official German aerial orthophotos (DOP20, 20 cm) with object detection.

**Status (November 2026): work in progress.** The image archive scripts and the dataset builder (`tile_and_chip.py`) work and are tested. Labelling is ongoing. The training, prediction and review modules are planned and not yet written. Code, structure and documentation may still change significantly.

## What the project does and why

Identifying wood industry sites provides crucial information for monitoring the timber market and allows for designing survey samples to gather empirical data on, e.g., wood resource use. Existing registries are incomplete and age quickly. The project is run by the Thünen Institute of Forestry (wood market research).

The **main objective is the reliable identification and georeferencing of wood industry sites in Germany** (such as sawmills, pulp plants and panel plants) from aerial imagery. An object detection model (YOLO first) finds candidate logyards and industry sites in DOP20 imagery; people then confirm or reject the candidates in QGIS.

**The deliverable is a reviewed, geo-referenced site register, not the model.** The model is the machinery that produces and updates the register. The compute module is replaceable, so other ML methods can be used and compared on the same holdout.

## How it is built

All code is one installable Python package, `woodsites` (in `src/woodsites`), with one subpackage per module. Modules only talk to each other through files; the layouts of these files are fixed in [`docs/contracts/`](docs/contracts/).

| Module | Task | Reads | Writes (in `data/`) |
|---|---|---|---|
| `module1_reference` | builds the reference set: fetches and freezes image tiles (`imagery`), people draw and check polygons in QGIS (`labelling`) | state WMS, LGLN COG | `data/reference/`: tiles + `manifest.csv`, polygon file with chip status, background list, holdout |
| `module2_detection` | turns the reference set into model inputs (`dataset`), later trains (`training`) and predicts (`prediction`) | `data/reference/` | `data/detection/`: datasets, model runs, `kandidaten_<lauf-id>.gpkg` |
| `module3_review` | holdout evaluation, model release, candidate review | candidates, holdout | `data/review/`: `freigabe.csv`, `pruefung.gpkg` (site register) |
| `core` | shared code: grid maths and IDs, config, readers for the reference files | – | – |

Implemented today: `core`, `module1_reference` (image archive scripts and the QGIS helper) and the dataset builder of `module2_detection`. Training, prediction and `module3_review` are planned. A module imports from `core`, never from another module.

```text
wood-industry-sites-detection/
├── src/woodsites/
│   ├── core/                 grid.py  config.py  polygons.py  sources.py     # shared by every module
│   ├── module1_reference/    model-independent: images and polygons
│   │   ├── imagery/          fetch_wms_chips.py  fetch_ni_cog_tiles.py  check_lgln_cog.py  check_lgln_stac.py
│   │   └── labelling/        fill_new_polygons_qgis.py                       # runs in the QGIS console
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

Each module folder has its own short README.

## Key terms

| Term | Meaning |
|---|---|
| **polygon** | drawn by hand in QGIS around wood (logyards, small wood) or an industry site; the ground truth |
| **tile** `f01_E…_N…` | 400 m stored image at 0.2 m, fetched once and frozen in the image archive |
| **chip** `g01_i…_j…` | 819.2 m model image at 0.4 m, cut from tiles; used for training and prediction |
| **label** | a box in a YOLO `.txt` file, made from the polygons |

## Requirements and setup

- **Windows laptop:** QGIS 3.40 with the **OSGeo4W Shell**, which provides Python 3.12, GDAL and numpy. Nothing else needs to be installed.
- **Other machines** (Linux, GPU VM, cluster): conda with [`environment.yml`](environment.yml):
  ```
  conda env create -f environment.yml
  conda activate woodsites
  ```

Then, in the OSGeo4W Shell or the conda environment (on Linux write the paths below with `/` instead of `\`):

1. Clone the repository and go into it:
   ```
   git clone https://github.com/TI-Wood-Resource-Monitoring/wood-industry-sites-detection.git
   cd wood-industry-sites-detection
   ```
2. Copy `configs\config.example.toml` to `configs\config.toml` and fill in the paths of your computer (or point the environment variable `WOODSITES_CONFIG` to your copy). `config.toml` is not part of the repository. Without it no data is reachable; that is expected on a fresh clone.
3. Run the tests:
   ```
   python tests\test_tile_and_chip.py
   ```
   The output must end with `ALL PASS`. The tests use synthetic data and need no network and no QGIS.
4. Optional: `pip install -e .` installs the package. It can then be imported from notebooks, and the short commands `woodsites-chips`, `woodsites-archive` and `woodsites-archive-ni` replace the long `python src\woodsites\...` lines.

## Usage overview

Run every command from the repository folder; the scripts find the package and `configs/config.toml` themselves.

| Command | What it does |
|---|---|
| `python src\woodsites\module2_detection\dataset\tile_and_chip.py check` | checks polygons, chips and tiles; writes nothing |
| `python src\woodsites\module1_reference\imagery\fetch_wms_chips.py plan` | works out which chips and tiles are needed; fetches nothing |
| `python src\woodsites\module1_reference\imagery\fetch_wms_chips.py run --only <state>` | fetches missing tiles for one state into the frozen archive |
| `python src\woodsites\module2_detection\dataset\tile_and_chip.py sync-chipcheck` | appends new chips to the chip status layer; never changes a status |
| `python src\woodsites\module2_detection\dataset\tile_and_chip.py train --dry-run` | builds a training dataset in geometry only (no images read, nothing written); drop `--dry-run` to write it |
| `python src\woodsites\module2_detection\dataset\tile_and_chip.py chips --chips <chip_id>,<chip_id>` | cuts prediction chips (no labels) |

QGIS rules, the labelling steps, background chips, Lower Saxony tiles from the LGLN COG, the field reference and troubleshooting are in [`docs/workflow.md`](docs/workflow.md).

## Data

No data is in this repository: polygons, imagery, datasets, model weights and QGIS projects stay outside it, at the locations given in your local `configs/config.toml`.

The imagery comes from the WMS services of the German states and, for Lower Saxony, from the LGLN open data. Each state has its own terms of use; check them before you use or pass on any image.

### For team members

To continue the work you additionally need:

- (a) the polygon GeoPackage with the chip status layer,
- (b) access to the frozen image archive,
- (c) the QGIS labelling project.

These are handed over internally on request. Then enter their locations in your local `configs/config.toml`.

## Documentation

| Document | Content |
|---|---|
| [`docs/structure.md`](docs/structure.md) | where the code lives, modules with inputs and outputs |
| [`docs/workflow.md`](docs/workflow.md) | every command in working order, QGIS rules, troubleshooting |
| [`docs/contracts/`](docs/contracts/) | file layouts passed between modules |

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). In short: no data and no personal or internal information in git, one branch per task, tests stay green, and a change to a file passed between modules updates `docs/contracts/` in the same pull request.

## AI assistance disclaimer

**This entire project uses the support of artificial intelligence (AI).** Final verification, scientific validity, and domain-specific integration remain managed and validated by the contributors to this repository.

## License

See [LICENSE](LICENSE).

## Contact

- GitHub organisation: [TI-Wood-Resource-Monitoring](https://github.com/TI-Wood-Resource-Monitoring)
- Questions and bug reports: [issue tracker](https://github.com/TI-Wood-Resource-Monitoring/wood-industry-sites-detection/issues)
