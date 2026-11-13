# data/ – local data, never committed

Git ignores everything in this folder except this file. It gives every user the same
default layout; the real locations are set in `configs/config.toml` and may point elsewhere
(for example an image archive on a network drive).

```text
data/
├── reference/     product of Module 1 – independent of any model
│   ├── dop20_polygons.gpkg      polygons + chip status (layer chip_check)
│   ├── background_g01.gpkg      background chips, checked by eye
│   ├── holdout.gpkg             planned
│   ├── dop20_labeling_qgz.qgz   QGIS labelling project (next to the polygon file: relative paths)
│   └── archive/                 frozen image tiles by state + manifest.csv (may live on a network drive)
├── detection/     product of Module 2 – specific to a model
│   ├── datasets/                d001_<date>/ … built by tile_and_chip.py
│   ├── runs/                    training runs and weights (planned)
│   └── candidates/              kandidaten_<lauf-id>.gpkg (planned)
└── review/        product of Module 3
                   freigabe.csv, pruefung.gpkg (planned)
```

Team members receive the reference files internally on request; they are not public.
