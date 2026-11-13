# Working steps and commands

Every command of the data pipeline in the order you need it, for the OSGeo4W Shell and the
QGIS Python console. **All shell commands are run from the repository folder** (`cd /d <repo>`);
the scripts find the shared library (`src/woodsites`) and `configs/config.toml` themselves.

---

## 0. Where things are

| What | Where |
|---|---|
| Scripts of the image archive | `src\woodsites\module1_reference\imagery\` |
| Chipping (training and prediction mode) | `src\woodsites\module2_detection\dataset\tile_and_chip.py` |
| QGIS helper for new polygons | `src\woodsites\module1_reference\labelling\fill_new_polygons_qgis.py` |
| Shared library | `src\woodsites\core\` |
| All paths and parameters | `configs\config.toml` (template `configs\config.example.toml`), or the file named in `WOODSITES_CONFIG` |
| Polygons + chip status (outside the repo) | `[paths] polygons_gpkg`: layers `dop20_polygons` and `chip_check` |
| Background chip list (outside the repo) | `[paths] background_gpkg` (created by `background`) |
| Frozen image archive (outside the repo) | `[paths] archive`: tiles per state, `manifest.csv`, `mosaic_f01.vrt`, `plan_f01.gpkg` |
| Training datasets (outside the repo) | `[paths] dataset_root`: `d00N_<date>\` |

Terms: **polygon** = drawn by hand; **tile** `f01_E…_N…` = 400 m stored image (0.2 m);
**chip** `g01_i…_j…` = 819.2 m model image (0.4 m), cut from tiles; **label** = box in a YOLO
`.txt`, made from the polygons.

---

## 1. Once per computer

1. Start the **OSGeo4W Shell** (comes with QGIS 3.40; has Python 3.12 + GDAL + numpy).
2. If the archive is on the institute network: connect the **VPN**. Keep the laptop on power and the lid open during long runs.
3. Go to the repository folder:
   ```
   cd /d <repo>
   ```
4. Copy `configs\config.example.toml` to `configs\config.toml` and fill in the paths of this computer.
5. Test the installation:
   ```
   python tests\test_tile_and_chip.py
   ```
   Must end with `ALL PASS`.

Optional: `pip install -e .` installs the package. It can then be imported from notebooks, and the short commands `woodsites-chips`, `woodsites-archive` and `woodsites-archive-ni` replace the long `python src\woodsites\...` lines below.

Most scripts print their own help: `python <script>.py --help`.

---

## 2. QGIS rules (the usual pitfalls)

- **Saving:** first "Save Layer Edits" (pencil menu), then Ctrl+S. Ctrl+S alone only saves the project, not the polygons.
- **Scripts see only saved edits.** QGIS keeps saved edits in `<polygons>.gpkg-wal`; the scripts read that too.
- **Before `plan`:** remove every layer from `plan_f01.gpkg` (right-click → Remove Layer; unticking is not enough).
- **Before `run`, `mosaic`, `background`:** remove the mosaic layer `mosaic_f01`. QGIS writes its own copy of the VRT back over the file otherwise. Add it again afterwards (symbology "No stretch").
- **Before `sync-chipcheck`:** `chip_check` must not be in edit mode.
- **Python console:** one statement per paste; paths as `r"…"`. After a QGIS restart, helpers must be run again.
- `plan_f01` layers and `background_g01` come with an outline-only style built in. If they still look filled: Layer Properties → Symbology → Style → Load Style → From Database.

---

## 3. Labelling a site (repeat per site)

**a) Open the site's chips.** In the attribute table of `chip_check`, filter e.g. `"site_ids" LIKE '%S0002%'`. Zoom to each chip (whole chip, not just the site).

**b) Draw every piece of visible wood in every chip**, on the mosaic `mosaic_f01` (the frozen archive, so image and label match):
- A polygon covers the area stocked with wood at the flight: piles plus the lanes between them. Empty yard surface stays out.
- Small amounts (single stacks, a few piles, leftover stock; rule of thumb < ~20 × 20 m) → `holz_klein`. Never leave wood undrawn inside a chip.
- **`category`**: leave **empty for `holz_klein`**; type `logyard_rough` for yards; `industry_site` only for industry outlines. Spelling exactly as here.
- **`triage_note`**: leave **empty for round wood**; otherwise `typ=schnittholz`, `typ=gemischt`, `typ=hackschnitzel` or `typ=unklar` (lower case, no spaces).
- Everything else stays empty — the helper fills it.

**c) Fill the attributes** (QGIS Python console, one line):
```
exec(open(r"<repo>\src\woodsites\module1_reference\labelling\fill_new_polygons_qgis.py", encoding="utf-8").read())
```
Fills every polygon with an empty `new_id`, `site_id` or `land`: `site_id` and `land` from the `industry_site` outline the polygon lies in (largest overlap), otherwise from the nearest polygon that has them; empty `category` → `holz_klein`, empty `triage_note` → `typ=rundholz` (a `typ=…` typed into `triage` by mistake is moved to `triage_note`); `herkunft = dop20_neu`; `new_id` kept if you typed one, otherwise `<site>_N<next number>` (starts at N01). Nothing is saved: check the printed table — a line with **CHECK:** needs a look (another site about as close, polygon overlaps two industry outlines, typed `new_id` does not match the site, value moved) — then Save Layer Edits + Ctrl+S.
Run it once per site, after finishing that site (it fills empty polygons everywhere).

**Two sites next to each other:**
- Keep them as two sites; never merge their polygons. A polygon belongs to the site whose `industry_site` outline it lies in — the helper does this. Wood outside both outlines: decide by hand where the helper says CHECK.
- Label **both** sites before marking any chip: a chip shared by both is `vollständig` only when the wood of both sites is drawn.
- Nothing else to do: the train/val split keeps overlapping chips together automatically, and a holdout must contain both sites.

**d) Update plan, tiles and chip list** (remove `plan_f01` layers and the mosaic layer first):
```
python src\woodsites\module2_detection\dataset\tile_and_chip.py check
python src\woodsites\module1_reference\imagery\fetch_wms_chips.py plan
python src\woodsites\module1_reference\imagery\fetch_wms_chips.py run --only <state>
python src\woodsites\module2_detection\dataset\tile_and_chip.py sync-chipcheck
python src\woodsites\module2_detection\dataset\tile_and_chip.py check
```
- `check` writes nothing; it lists errors (must be 0) and warnings: chips missing in `chip_check`, chips with missing tiles, polygons that would never get a box.
- `plan` stops if a polygon has an empty or misspelled `new_id` / `site_id` / `land` → step c.
- `run --only <state>` fetches only tiles that are missing (state name exactly as in §9). Not needed if `check` shows no missing tiles.
- `sync-chipcheck` appends new chips to `chip_check` (status empty); it never changes a status.
- The second `check` should show no missing chips and no missing tiles.

**e) Mark the chips** in `chip_check`, field `status`:
- `vollständig` — every piece of wood in the whole chip is drawn (also other sites' wood and the chip edges). Only these go into training.
- `unsicher` — drawn, but something is doubtful (left out unless `--include-unsicher`).
- empty — not checked yet.

Save Layer Edits + Ctrl+S. Add the mosaic and `chips_g01` back.

---

## 4. Background chips (random areas without wood)

```
python src\woodsites\module1_reference\imagery\fetch_wms_chips.py background --n 3
python src\woodsites\module1_reference\imagery\fetch_wms_chips.py background
```
- First a small test (`--n 3`), then the default (10 % of the label chips, at least one per state). Options: `--only <state>`, `--seed`.
- Chips are ≥ 2 km from every polygon; tiles are fetched at 0.2 m like label tiles.
- Open `background_g01.gpkg` over the mosaic and set `status` per chip: `ok` (no wood) / `holz` (wood found: draw it or drop the chip) / `verwerfen`. Only `ok` is used.
- Running it again keeps the chips and your statuses and only adds what is missing.

---

## 5. Building a training dataset

```
python src\woodsites\module2_detection\dataset\tile_and_chip.py train --dry-run
python src\woodsites\module2_detection\dataset\tile_and_chip.py train
python src\woodsites\module2_detection\dataset\tile_and_chip.py roundtrip d00N_<date>
```
- `--dry-run`: geometry only (boxes, masks, missing tiles, split); reads no images, writes nothing.
- `train` writes `<dataset_root>\d00N_<date>\`: `images\train|val\*.tif` (georeferenced), `labels\…\*.txt` (YOLO), `data.yaml`, `chip_index.gpkg`, `snapshot\` (frozen copy of the inputs + sha256), `params.json`, `report.txt` (what was left out and why). A new run never overwrites an old dataset.
- Options: `--holz-klein positive|background|mask` (default from config: `positive` = like `logyard_rough`), `--include-unsicher`, `--limit N` (quick test with the first N chips).
- **Visual check in QGIS:** open some chip `.tif` and the layers `labels` and `masks` of `chip_index.gpkg` — every box must sit on its wood (this is the Y-axis check). Grey patches = parts of yards that were mostly in a neighbouring chip.
- `roundtrip` converts every YOLO box back to map coordinates; must print `OK`.

Rules built in: a box is written if ≥ 50 % of the polygon or ≥ 1 ha of it lies in the chip; otherwise the visible part is greyed out (RGB 114). Chips with missing tiles, > 1 % white/black pixels or > 25 % grey are left out. Train/val split 15 %, whole groups of overlapping chips. The holdout (`holdout_gpkg` in config, once agreed) is never written.

---

## 6. Prediction chips (no labels, no grey)

```
python src\woodsites\module2_detection\dataset\tile_and_chip.py chips --chips <chip_id>,<chip_id>
python src\woodsites\module2_detection\dataset\tile_and_chip.py chips --bbox <minx>,<miny>,<maxx>,<maxy>
python src\woodsites\module2_detection\dataset\tile_and_chip.py chips --area some_area.gpkg --out <folder>
```
Same reading as training. Chip IDs may be new (`g01_i…_j…`) or old (`g01_E…_N…`).

---

## 7. Image archive maintenance (`src\woodsites\module1_reference\imagery\fetch_wms_chips.py`)

| Command | What it does |
|---|---|
| `caps` | asks every state WMS what it allows (size, formats, CRS) |
| `plan` | which chips/tiles are needed → `plan_f01.gpkg` in the archive (fetches nothing) |
| `test` | one tile per state, to look at |
| `run` | fetch all missing tiles (resumable; `--only <state>`, `--limit N`) |
| `probe --only <state>` | try request variants when a state fails |
| `redate` | re-read flight dates from the stored raw text |
| `mosaic` | rebuild `mosaic_f01.vrt` (remove the layer in QGIS first) |
| `background` | background chips (§4) |
| `--url <url> --layer <name>` with `--only` | try another WMS for one state, once |

Never overwrites a tile; writes `*.part` first; keeps Windows awake and waits up to 30 min if the archive drive disappears. Errors go to `errors.csv` in the archive.

**Lower Saxony from the LGLN COG** (when the NI WMS is down; same tiles, original pixels):
```
python src\woodsites\module1_reference\imagery\fetch_ni_cog_tiles.py list
python src\woodsites\module1_reference\imagery\fetch_ni_cog_tiles.py run --limit 1
python src\woodsites\module1_reference\imagery\fetch_ni_cog_tiles.py run
python src\woodsites\module1_reference\imagery\fetch_ni_cog_tiles.py run --date <YYYY-MM-DD>
```
Checks of the LGLN service (test point as `E N` in EPSG:25832, or `[checks] test_point` in the config):
```
python src\woodsites\module1_reference\imagery\check_lgln_cog.py <E> <N>
python src\woodsites\module1_reference\imagery\check_lgln_stac.py <E> <N>
```

---

## 8. Field and value reference

`dop20_polygons` (EPSG:25832):

| Field | Values |
|---|---|
| `new_id` | `S0001_L01` (triaged yard), `S0001_I01` (industry), `S0001_N01` (new, filled by the helper) |
| `site_id` | `S0001` … |
| `land` | exactly one of: `Niedersachsen`, `Nordrhein-Westfalen`, `Brandenburg`, `Baden-Württemberg`, `Rheinland-Pfalz`, `Sachsen`, `Thüringen`, `Bayern`, `Hessen`, `Mecklenburg-Vorpommern`, `Saarland`, `Sachsen-Anhalt` |
| `category` | `logyard_rough`, `industry_site`, `holz_klein` |
| `triage` | `A`, `B`, `C` (old polygons only; C = never a label); empty for new ones |
| `triage_note` | `typ=rundholz` / `schnittholz` / `gemischt` / `hackschnitzel` / `unklar`, plus free text |
| `herkunft` | `dop20_neu` for new polygons |

`chip_check.status`: `vollständig` / `unsicher` / empty. `background_g01.status`: `ok` / `holz` / `verwerfen` / empty.

---

## 9. Troubleshooting

| Message / problem | Cause and fix |
|---|---|
| `can't open file …` | wrong folder → `cd /d <repo>` and give the script with its folder, e.g. `python src\woodsites\module1_reference\imagery\fetch_wms_chips.py` |
| `config file not found` | `configs\config.toml` missing (copy the example), or `WOODSITES_CONFIG` points to a wrong file |
| `No module named 'woodsites'` | the script was moved out of the repository; run it from its place in the repo |
| `plan_f01.gpkg … is in use` | remove the `plan_f01` layers in QGIS, run again |
| `empty or unknown new_id / site_id / land` | fill the polygons (§3c), check spelling of `land`, save, run again |
| `cannot write chip_check` | stop editing `chip_check` in QGIS (save or discard), run again |
| mosaic in QGIS lacks new tiles | QGIS overwrote the VRT: remove the layer, `python src\woodsites\module1_reference\imagery\fetch_wms_chips.py mosaic`, add it again |
| archive drive disappears / run stops | VPN dropped (standby). Reconnect, start the same command again — finished tiles are kept |
| a state's WMS fails (maintenance page, error 86 …) | check the layer in QGIS; try later; `probe --only <state>`; Lower Saxony: `fetch_ni_cog_tiles.py` |
| LGLN host names not found | network DNS; the scripts retry and use LGLN's own host names |
| `check` warns "never … in any chip" | a polygon would only ever be greyed out — look at its size/position |
| dataset report lists chips "status 'empty'" | set `vollständig` in `chip_check` (§3e) |
| `fetch_wms_chips.py --help` crashes (`%o format`) | known bug in a help text; the commands themselves work |

---

## 10. Parameters (`configs\config.toml`)

`[paths]` polygons_gpkg, archive, background_gpkg, dataset_root, holdout_gpkg (empty = none).
`[background]` share 0.10, min_dist_m 2000, seed 1.
`[tile_and_chip]` holz_klein `positive`, min_visible 0.5, min_visible_m2 10000, mask_value 114, mask_grow_px 2, min_box_px 4, max_mask_share 0.25, max_empty_share 0.01, chip_status_ok `['vollständig']`, val_share 0.15, seed 1.
`[checks]` test_point `[E, N]` (optional).
