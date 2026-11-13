# `kandidaten_<lauf-id>.gpkg` – detection candidates (draft)

Output of Module 2 (prediction run), input of Module 3 (review). Written once, never edited;
review decisions go into `pruefung.gpkg`. Every Module 2 implementation must produce exactly
this layout; `module3_review` will contain a checker for it.

- Geometry: **polygon**, EPSG:25832, valid, one feature per candidate
- `kandidat_id` – unique within the file
- `konfidenz` – 0 … 1
- `klasse` – e.g. `logyard`
- `modell_version` – e.g. `m001`
- `datensatz_version` – e.g. `d004`
- `code_version` – git commit of the code that produced the file
- `bildflugjahr` – flight year of the imagery
- `chip_ids` – chips the candidate was detected in, `;`-separated

The holdout test run writes the same layout as `kandidaten_holdout_<modell>.gpkg`.
