# Module 2 · Detection – replaceable as a whole

Turns the reference set of Module 1 into whatever a particular model needs, trains and
predicts. Fixed are only the input (the reference set: tiles + polygon files) and the output
(`kandidaten_<lauf-id>.gpkg`, see [`docs/contracts/kandidaten.md`](../../../docs/contracts/kandidaten.md)).
Everything in between – including the ML method – can be replaced. Runs without QGIS,
first locally, later on a GPU VM or cluster.

| Folder | Diagram | Status |
|---|---|---|
| `dataset/` | `tile_and_chip.py`: chips and labels, training **and** prediction mode (one script, two modes). Only `writers/yolo.py` knows the YOLO format | implemented |
| `training/` | 2a · Training on known sites: split, model training, holdout test run | planned |
| `training/yolo/` | YOLO as the first model; other methods go next to it | planned |
| `prediction/` | 2b · Prediction Lower Saxony: model prediction on the chips selected by Module 1's prefilter, `postprocess_merge.py` | planned |

`tile_and_chip.py` sits above 2a and 2b on purpose: both must cut chips in exactly the same way.

Run from the repository folder: `python src\woodsites\module2_detection\dataset\tile_and_chip.py check`.

## Planned: `training/` (2a · known sites, Germany-wide)

Planned content:
- training script per model (first: `yolo/`), reading a dataset `d00N` built by
  `dataset/tile_and_chip.py train`
- model weights are versioned as `m001`, `m002` … (stored outside the repository)
- test run on the holdout → `kandidaten_holdout_<modell>.gpkg`, same chain as 2b

The train/validation split is already done by `tile_and_chip.py` (spatial, whole groups of
overlapping chips; the holdout is excluded before that).

### `training/yolo/` – first implementation

Planned: training and prediction scripts for Ultralytics YOLO, reading the YOLO dataset
layout written by `logyard.writers.yolo`.

Note: Ultralytics is licensed under AGPL-3.0; the licensing question is open.

## Planned: `prediction/` (2b · Lower Saxony, separate run)

Planned content:
- input: the list of chips to look at, written by the prefilter of Module 1 (it is independent
  of the model, so it is not part of this module)
- `predict.py` – stage 2: model prediction with a released model (see `freigabe.csv`)
- `postprocess_merge.py` – detections from overlapping chips → map coordinates, merge
  duplicates and join fragments of large yards → `kandidaten_<lauf-id>.gpkg`

Imagery: LGLN COG, read directly (no download), flight date from the STAC catalogue.
Chips: `dataset/tile_and_chip.py chips` (prediction mode).
