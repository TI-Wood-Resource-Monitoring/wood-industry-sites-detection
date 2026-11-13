# `freigabe.csv` – model release decisions (draft)

One row per evaluated model, written after `evaluate_holdout.py` and a human decision.
Only a released model is used for the Lower Saxony prediction run.

Planned columns: `modell_version`, `datensatz_version`, `code_version`, holdout metrics
(yards found / missed / false alarms), `freigegeben` (ja / nein), `begruendung`, `datum`.
