# Module 3 · Review

People decide: models are released, candidates are confirmed or rejected in QGIS.

Planned content:
- `evaluation/evaluate_holdout.py` – compares `kandidaten_holdout_<modell>.gpkg` with `holdout.gpkg`;
  the same yardstick for every model, independent of the ML framework
- `evaluation/release` – writing `freigabe.csv` (values, yes/no, reason)
- `review/` – QGIS review helpers: confirm / reject, flag typical confusers → `pruefung.gpkg`
- a checker for the `kandidaten` contract

File layouts: [`docs/contracts/`](../../../docs/contracts/).
