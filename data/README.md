# data/ – local data, never committed

Git ignores everything in this folder except this file. It gives every user the same
default layout; the real locations are set in `configs/config.toml` and may point elsewhere
(for example an image archive on a network drive).

```text
data/
├── raw/           output of module 1 (data acquisition) – independent of any model
│   ├── dop20_polygons.gpkg      polygons + chip status (layer chip_check)
│   ├── background_g01.gpkg      background chips, checked by eye (planned)
│   ├── holdout.gpkg             planned
│   ├── dop20_labeling_qgz.qgz   QGIS labelling project (next to the polygon file: relative paths)
│   └── archive/                 frozen image tiles by state + manifest.csv (may live on a network drive)
└── processed/     output of module 2 (data preparation) – specific to a model
    └── datasets/                datasets for model training
```

A third subfolder for the later steps (training runs, results, review) will be added when
its name is decided.

Team members receive the files in `raw/` internally on request; they are not public.
