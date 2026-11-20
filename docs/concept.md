# Architecture concept

How the system is built and why. Project goals, background and roadmap are in the
[README](../README.md).

**Status: early planning.** Nothing described here is built yet. The two leading documents are:

- [`code-architecture.drawio`](code-architecture.drawio), tab *v3-architecture*: components and order of execution
- [`oop-roles.md`](oop-roles.md): what each role does, how it looks in Python, protocols, logging

If this document and those two disagree, those two apply. Decisions marked ✅ are fixed; ⬜ are open.

---

## 1. Design principles

- ✅ **Modules exchange files only.** A module reads from `data/` and writes to `data/`. No module imports code from another module.
- ✅ **One place builds everything.** `main` reads the config and calls the factory. The factory creates all objects once and wires them together. No other code creates adapters or repositories.
- ✅ **The coordinator knows only protocols.** It controls the order of steps and never sees which concrete class sits behind types, e.g.`PolygonSource`, `ImageSource`, `ImageStore`.
- ✅ **Logic and I/O are separate.** Pure functions (e.g.`plan_tiles`, `to_geotiff`) hold the logic: data in, result out. Adapters and repositories do all reading and writing (disk, WMS).
- ✅ **Settings live only in config.** No path, URL or parameter is hard-coded.
- ✅ **The log is for people.** Anything the program needs later goes into a return value (`RunReport`) or `metadata.db`, never into the log.

## 2. Modules and data flow (work in progress)

| Module           | Package              | Reads                                             | Writes                                                       | State   |
| ---------------- | -------------------- | ------------------------------------------------- | ------------------------------------------------------------ | ------- |
| 1 · Acquisition | `src/acquisition/` | polygon GeoPackage, WMS server                    | `data/raw/images/*.tif`, `data/raw/metadata.db`          | planned |
| 2 · Preparation | `src/preparation/` | `data/raw/`                                     | `data/processed/training/`, `data/processed/prediction/` | later   |
| 3 · Training    | `src/training/`    | `data/processed/training/`                      | `data/weights/`                                            | later   |
| 4 · Prediction  | `src/prediction/`  | `data/processed/prediction/`, `data/weights/` | `data/results/`                                            | later   |
| 5 · Review      | `src/review/`      | `data/results/`                                 | `data/review/`                                             | later   |

Each module is a separate program with its own `main`, factory and coordinator (§3 shows Module 1). Modules run one after another and hand over files only, so each one can be built, tested and replaced on its own.

- **1 · Acquisition:** the only module that fetches imagery, both for training (tiles planned from polygons) and for prediction (tiles planned from an area, ⬜ §5).
- **2 · Preparation:** turns raw tiles into the format the model needs. Training and prediction data go into separate folders, so they never mix.
- **3 · Training:** reads only `processed/training/`. Each weights file records which dataset it was trained on.
- **4 · Prediction:** reads `processed/prediction/` and one chosen weights version, never training data. Each result records the weights version it came from.
- **5 · Review:** people confirm or reject results. Their decisions go into `data/review/`, separate from `data/results/`, so a new prediction run never overwrites them (feedback into Module 1: ⬜ §5).

```text
data/
├── raw/                  output of module 1
│   ├── geopkg/           polygon GeoPackage, drawn by hand
│   ├── images/           GeoTIFF tiles (*.tif only)
│   └── metadata.db       image ↔ polygon, meta info
├── processed/            output of module 2, in the format the model needs
│   ├── training/
│   └── prediction/
├── weights/              output of module 3: trained models
├── results/              output of module 4: detections
└── review/               output of module 5: human decisions on the results
logs/<module>.log         one log file per module (git-ignored)
authentification/         credentials per WMS service: account, password (git-ignored)
```

## 3. Module 1 · Acquisition (work in progress)

Plan tiles from polygons, then fetch, georeference and save each tile.

### Setup (once)

1. `main` reads the config and the credentials (`read_settings()`) and calls `configure_logging()`.
2. `main` calls `create_coordinator(settings)`.
3. The factory builds `PolygonFile`, `WmsClient` and `FileImageStore` and injects them into `ImageAcquisitionCoordinator`.

### Execution (per run)

`run() → RunReport`:

| Step | Call                                                                                      | Result                                               |
| ---- | ----------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| ⓪   | `read_polygons()` via `PolygonSource`                                                 | polygons                                             |
| ⓪   | `plan_tiles(polygons)`: filter polygons, index chips, chips in polygons, chips in tiles | `tile_list`                                        |
| ①   | per tile: `fetch(tile)` via `ImageSource`                                             | `RawImage`                                         |
| ②   | `to_geotiff(raw)`                                                                       | `GeoTIFF`                                          |
| ③   | `save(geotiff)` via `ImageStore`                                                      | file in `data/raw/images/`, row in `metadata.db` |

### Components

| Role        | Name                                               | Task                                                                     |
| ----------- | -------------------------------------------------- | ------------------------------------------------------------------------ |
| entry point | `main`                                           | reads config and credentials, sets up logging, calls the factory, starts the run |
| factory     | `create_coordinator()`                           | builds all objects once and wires them together                          |
| coordinator | `ImageAcquisitionCoordinator`                    | controls the order ⓪–③                                                |
| protocol    | `PolygonSource`, `ImageSource`, `ImageStore` | contracts used by the coordinator                                        |
| function    | `plan_tiles()`, `to_geotiff()`                 | tile planning; georeferencing                                            |
| repository  | `PolygonFile`                                    | reads the GeoPackage, technical checks                                   |
| adapter     | `WmsClient`                                      | WMS `GetMap` over HTTP, one per service; receives URL, account and password at creation; sends auth per request, never in the URL or log |
| repository  | `FileImageStore`                                 | writes GeoTIFF files and `metadata.db` rows                            |

## 4. Cross-cutting

- **Config:** a `Settings` object (`@dataclass(frozen=True)`) with paths, WMS URL, `log_file` and `log_overwrite` from `configs/`, plus account and password from `authentification/`. The password field uses `repr=False`, so it never shows up when settings are printed or logged. `main` passes `Settings` to the factory.
- **Logging:** each code module has `getLogger(__name__)`, and the `main` of each pipeline module sets it up once, writing to its own file (`logs/<module>.log`): console at INFO, file at DEBUG. `log_overwrite=True` starts an empty file; `False` appends. Details: [`oop-roles.md` §3](oop-roles.md#3-logging).
- **Errors:** log *or* raise, not both. Adapters raise, and the coordinator handles and logs. Secrets never appear in the log.
- **Testing:**
  - functions: tested directly with test data;
  - coordinator: tested with fakes behind the protocols;
  - log output: checked with pytest's `caplog`.
- **Protocols:** ✅ defined at the consumer, i.e. in the coordinator's module, and kept small. ✅ A type checker (`mypy` or `pyright`) checks them.

## 5. Open decisions

| Topic                  | State                                                                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Package path           | ⬜ flat (`src/acquisition/`, `src/preparation/`, …) or below a common package, e.g. `src/woodsites/`              |
| Shared code            | ⬜ where code used by several modules lives (e.g. grid and tile IDs, domain types), without modules importing each other |
| WMS password           | ✅ stored in `authentification/` (git-ignored), never in `configs/` or in a log; read into `Settings` by `read_settings()` in `main`. ⬜ file format and per-service structure |
| Several WMS services   | ⬜ the factory builds one `WmsClient` per service, each with its own credentials                                         |
| `metadata.db`        | ⬜ format (e.g. SQLite) and fields (source, fetch time, checksum, flight date, image ↔ polygon)                         |
| Resume after a crash   | ⬜ skip tiles already in `metadata.db`; never overwrite an existing tile                                               |
| Safe writes            | ⬜ write to a temporary file, rename when complete, then add the row                                                     |
| WMS failures           | ⬜ timeouts, retries with backoff, recognising error responses with HTTP 200                                             |
| Domain types           | ⬜ small dataclasses for `Tile`, `Polygon`, `RawImage`, `GeoTIFF`, `RunReport` instead of dictionaries         |
| Command line           | ⬜ e.g. `--dry-run` (plan only), `--limit`                                                                           |
| Prediction imagery     | ⬜ second tile plan in Module 1: tiles for a whole area instead of from polygons                                         |
| Module 2 internals     | ⬜ chips, labels, dataset format for the model, split into training and validation                                       |
| Modules 3–5 internals | ⬜ framework and weights format (3), result format (4), review tool (5)                                                  |
| Evaluation             | ⬜ which module measures model quality against a test set (3 or 5)                                                       |
| Review feedback        | ⬜ whether and how review decisions flow back as new polygons into Module 1                                              |
| Running the pipeline   | ⬜ one command per module, or a small runner that calls the modules in order                                             |
| Tooling                | ⬜ `pyproject.toml`, ruff, pytest, type checker in CI                                                                  |

## 6. Glossary

- **Tile:** an image available on the WMS server; the unit that is fetched and stored.
- **Chip:** a selected image detail, cut for the model.
- **Polygon:** a site outline drawn by hand, stored in the GeoPackage.
- **GeoTIFF:** an image file with embedded georeference.
- **GeoPackage:** an SQLite-based file format for vector data.
- **WMS / GetMap:** a web service that renders a requested map rectangle as an image.
- **`metadata.db`:** links each image to its polygons and holds its meta info.
- **`RunReport`:** the result of one run (fetched, skipped, failed).
- **Weights:** the trained model, i.e. the output of training and the input of prediction.
- **Results:** detections produced by prediction, before review.
- **Protocol, adapter, repository, factory, coordinator:** see [`oop-roles.md`](oop-roles.md).
