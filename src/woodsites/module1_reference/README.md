# Module 1 · Reference

Everything that is independent of the model: the frozen image tiles and the hand-drawn
polygons. Its product is the **reference set** in `data/reference/` (or wherever
`configs/config.toml` points):

| Part of the product | File | Made by |
|---|---|---|
| image tiles with provenance | `archive/` + `manifest.csv` | `imagery/` |
| polygons and chip status | `dop20_polygons.gpkg` (layers `dop20_polygons`, `chip_check`) | people in QGIS, `labelling/` |
| background chips, checked by eye | `background_g01.gpkg` | `imagery/` (drawn), people (checked) |
| holdout (planned) | `holdout.gpkg` | people |

None of these files is in the repository.

## `imagery/` – fetch tiles once and freeze them

Tiles are fetched **once** from the state WMS services (Lower Saxony: from the LGLN COG) and
frozen as georeferenced GeoTIFFs with a `manifest.csv`. Training never reads from a WMS.
Runs in the OSGeo4W Shell, without QGIS.

| Script | What it does |
|---|---|
| `fetch_wms_chips.py` | `caps` · `plan` · `test` · `run` · `probe` · `redate` · `mosaic` · `background` |
| `fetch_ni_cog_tiles.py` | Lower Saxony tiles from the LGLN COG (`list` · `run`) – reuses `fetch_wms_chips.py` |
| `check_lgln_cog.py` | is the LGLN COG directly readable? |
| `check_lgln_stac.py` | which flights does the LGLN STAC catalogue list at a point? |

Run from the repository folder: `python src\woodsites\module1_reference\imagery\fetch_wms_chips.py plan`.
`fetch_ni_cog_tiles.py` imports `fetch_wms_chips.py`, so both must stay in the same folder.
Archive layout: [`docs/contracts/manifest.md`](../../../docs/contracts/manifest.md).

## `labelling/` – QGIS helpers

People draw polygons in QGIS on the frozen image mosaic. This is the ground truth.

| Script | Where it runs | What it does |
|---|---|---|
| `fill_new_polygons_qgis.py` | QGIS Python console | fills `new_id`, `site_id`, `land`, `herkunft`, `category`, `triage_note` of newly drawn polygons |

Labelling rules and the field reference: [`docs/workflow.md`](../../../docs/workflow.md).

## Planned

`prefilter/` – which chips are worth looking at in a state-wide run (official land-use data).
It is independent of the model, so it belongs here.
