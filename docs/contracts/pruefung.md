# `pruefung.gpkg` – review decisions and the site register (draft)

- Layer `entscheidungen`: one row per reviewed candidate – `kandidat_id`, source file,
  decision (bestätigt / verworfen), flag "typische Verwechslung", date.
- Layer `standorte_bestaetigt`: confirmed sites with a stable site ID – **the site register,
  the actual product**.

Rejected candidates flagged as typical confusers become hard negatives in Module 1 – never
from the holdout. A confirmed site only becomes a training label if a polygon is drawn
deliberately in Module 1.
