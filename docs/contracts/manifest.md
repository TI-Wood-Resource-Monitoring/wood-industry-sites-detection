# `manifest.csv` – image archive index (implemented)

One row per stored tile `f01_E…_N…` (400 m × 400 m, 2000 × 2000 px at 0.2 m, EPSG:25832).
Written by `module1_reference/imagery/fetch_wms_chips.py` and `fetch_ni_cog_tiles.py`; read by
`module2_detection/dataset/tile_and_chip.py`.

| Column | Meaning |
|---|---|
| `tile_id` | `f01_E<easting:07d>_N<northing:07d>`, lower-left corner in metres |
| `land` | federal state (exact spelling as in the scripts) |
| `site_ids` | sites the tile was fetched for, `;`-separated |
| `minx`, `miny`, `maxx`, `maxy`, `epsg` | bounds in EPSG:25832 |
| `native_epsg` | CRS the server delivered in originally |
| `px`, `gsd_m` | pixel count per side, ground sampling distance |
| `wms_url`, `layer`, `wms_version`, `format`, `n_requests` | how the tile was requested |
| `fetched_utc`, `seconds` | when and how long |
| `file`, `bytes`, `sha256` | stored file and its checksum |
| `leer_anteil` | share of empty (white/black) pixels |
| `info_layer`, `bildflug`, `bildflug_feld`, `bildflug_raw` | flight date and where it came from |
| `note` | e.g. `source=LGLN COG`, `background g01_…` |

A tile is never overwritten; a new flight means a new archive version.
