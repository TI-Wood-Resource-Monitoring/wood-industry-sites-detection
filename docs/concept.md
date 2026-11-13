# Concept: detecting wood industry sites and logyards in aerial imagery

General project concept (public version, November 2026). It explains what the project is
for, how the system is designed and why. Commands are in [`workflow.md`](workflow.md), the
code layout in [`structure.md`](structure.md), the design of the dataset builder in
[`design-chipping.md`](design-chipping.md).

Decisions marked ✅ are fixed; ⬜ are open.

---

## 1. Summary

Wood-market research needs to know where wood-related industry operates. Existing registries
are incomplete and age quickly. This project builds a detection system that finds wood
industry sites and logyards in official aerial orthophotos (DOP20, 20 cm ground resolution)
with deep-learning object detection, and delivers the results as a curated, geo-referenced
**site register**.

**The deliverable is the site register, not the model.** The model is the machinery that
produces the register and keeps it up to date. The first model family is YOLO; the compute
module is replaceable as a whole, so other methods can be compared on the same test data.

## 2. Goals and non-goals

**Goals**
- Detect logyards (and, in a cascade, industry sites and later individual log piles) in DOP20.
- Scale from a small prototype to one federal state (Lower Saxony first), later more.
- Produce a reviewable, versioned GIS layer of candidate sites with confidence scores.
- Keep a person in the loop: every candidate is confirmed or rejected before it enters the register.
- Keep every result reproducible: a prediction can be traced to model version, dataset
  version, imagery and code version.

**Non-goals (for now)**
- Monitoring *current* wood stocks. DOP flights repeat every 2–3 years, so a detection shows
  the state at the flight date (see §9).
- Real-time or on-demand detection.
- A public-facing product. Users are researchers.

## 3. Starting point

A proof of concept on a laptop (QGIS, YOLOv8 nano, 10 image tiles from a basemap) showed that
the chain works end to end:

**polygons → image tiles → chips → YOLO labels → training → prediction → GIS layer.**

It also showed what does not carry over: the basemap imagery is not licensable and undated,
the dataset was tiny, every step was manual, and the validation images came from the same
site as the training images, so its metrics mean nothing.

When the hand-drawn polygons were checked against DOP20, 102 of 107 were still valid, but
two thirds of the logyards had to be redrawn because the wood had moved within 2–3 years.
Two consequences shape the design: a label is only valid for the image it was drawn on, and
imagery must be frozen together with the labels.

## 4. System design

### Modules

The system has three modules. Modules exchange **files only**; the layouts are fixed in
[`contracts/`](contracts/).

| Module | Task | Reads | Writes |
|---|---|---|---|
| Module 1 · Reference | fetch image tiles once and freeze them; people draw and check polygons in QGIS | state WMS, LGLN COG | the reference set: tiles with `manifest.csv`, polygon file with chip status, background list, holdout |
| Module 2 · Detection | model inputs (chips and labels), training, prediction | the reference set | candidates file |
| Module 3 · Review | holdout evaluation, model release, candidate review | candidates, holdout | release table, site register |

✅ **Module 1 ends with the reference set; everything model-specific is Module 2.** The
holdout is part of the reference set because it must be the same for every model.

✅ **Module 2 is replaceable as a whole.** Everything framework-specific (YOLO label files,
dataset split, training) is its internal business. Fixed are only its inputs and its output,
a candidates file with a fixed schema (geometry, candidate ID, confidence, model version,
dataset version, flight year). A different method means a different Module 2; Modules 1 and 3
stay unchanged, and every method is measured with the same yardstick.

### Detection cascade

✅ Two stages, coarse to fine:

1. **Prefilter.** Official land-use data (industrial and commercial areas, plus a buffer)
   decides which chips are processed at all. Tuned for high recall: a site missed here is
   never seen again.
2. **Logyard detection** on the remaining chips, followed by human review.

A third stage, single log piles at full resolution inside confirmed yards, is deferred.
Cascades multiply misses, so early stages are permissive and precision is recovered later.

### Review and feedback

Review is binary: **confirmed** or **rejected**. Confirmed sites enter the register. A
rejected candidate that is a typical confuser (gravel, compost, scrap) can become a hard
negative for training. New training labels are always drawn deliberately in Module 1, never
produced as a side effect of review. Human decisions are stored separately from model output,
so a new run can never overwrite them.

## 5. Key design decisions

### Imagery

- ✅ **Training imagery from all states with labels, prediction in Lower Saxony first.** The
  known sites are spread over twelve states; too few lie in Lower Saxony to train there alone.
- ✅ **A frozen archive.** Training images are fetched once from the states' WMS services and
  stored as GeoTIFF tiles with a manifest (source, time, checksum, flight date where the
  service provides it). Training never reads from a live service.
- ✅ **Lower Saxony is read directly** from the state's Cloud Optimized GeoTIFFs (LGLN open
  data), located through its STAC catalogue. No bulk download is needed.
- ⬜ Training pixels (WMS, JPEG) and prediction pixels (COG originals) differ. A pixel
  comparison on identical areas decides whether this needs action.

### Grids

Two grids, both defined by the project, both in EPSG:25832 and on the same 0.2 m pixel lattice:

| Term | Size | Step | Role |
|---|---|---|---|
| **Tile** `f01` | 400 m = 2000 px at 0.2 m | 400 m, no overlap | storage unit of the archive |
| **Chip** `g01` | 819.2 m = 2048 px at 0.4 m | 614.4 m (25 % overlap) | what the model sees, in training and prediction |

Chip IDs are index-based (`g01_i…_j…`) and identical in training and prediction for the same
place. Cutting chips from tiles never shifts a pixel; the only resampling is the deliberate
step from 0.2 m to 0.4 m.

**Known limitation:** with 25 % overlap an object is guaranteed to be whole in one chip only
up to 205 m. Larger yards can be split, so the post-processing must join fragments from
neighbouring chips, not only remove duplicates.

### Labels

- ✅ **Boxes first.** Axis-aligned bounding boxes are the default. Because the ground truth is
  polygons, oriented boxes and segmentation can be generated from the same data and compared later.
- ✅ **What a polygon covers:** the area stocked with wood at the flight date (piles and the
  lanes between them). Empty yard surface is left out.
- ✅ **Complete annotation:** every wood store visible in a training chip is drawn, not only
  the listed site. Unlabelled wood would teach the model that wood is background.
- ✅ **Small wood** (single stacks, residual stock) is drawn with its own category
  `holz_klein`. How it is used (as a positive, as background, or masked) is a parameter of the
  dataset builder and is compared experimentally.
- ✅ **Chip borders:** a polygon cut by the chip border becomes a label if at least half of it,
  or at least one hectare, lies inside. Otherwise its visible part is masked in grey, so it
  counts neither as object nor as background.
- ✅ **One class** (`logyard`) in the first runs. A storage-type note on each polygon allows a
  later split.

### Evaluation

✅ Three separate sets:

| Set | Purpose | May drive decisions? |
|---|---|---|
| Training | the model learns from it | yes |
| Validation | choose epochs, thresholds, model versions | yes |
| Holdout | measure and report only | **no** |

The holdout is defined in Module 1, frozen and versioned, and consists of whole sites;
neighbouring sites stay together. False alarms from validation or holdout are never fed back
into training. Module 3 compares a test run with the holdout by one fixed method (sites
found, sites missed, false alarms), and a person decides whether a model is released. Only
released models run state-wide.

⬜ The holdout sites are not chosen yet. A false-alarm rate per km² becomes measurable only
once a contiguous, fully reviewed area exists.

### Background

✅ The first training includes about 10 % background chips without labels, from all states,
far from known sites and checked by eye. Later, hard negatives are mined in a pilot region:
run the model, review its most confident false alarms, add the typical confusers.

### Reproducibility

✅ All paths and parameters come from one config file; no script contains a path. Every
training dataset stores a frozen copy of the polygons and status tables it was built from,
with checksums.

## 6. Open decisions

| Topic | State |
|---|---|
| Model size and version | ⬜ decided empirically once GPU compute is available |
| Detection framework and its licence | ⬜ Ultralytics YOLO is AGPL-3.0; to be clarified before YOLO-specific code is published here. Because Module 2 is replaceable, a permissively licensed framework remains an option. |
| Compute | ⬜ training and the state-wide run need a GPU; the route is being clarified |
| Results storage | ⬜ GeoPackage files now; a database when several people review |
| Experiment tracking | ⬜ naming conventions and run folders now; a tracking tool when runs multiply |
| Review interface | ⬜ QGIS now; a lightweight web view is a later option |

## 7. Roadmap (phases, not dates)

| Phase | Content | State |
|---|---|---|
| 0 · Groundwork | check old polygons against DOP20; image archive; grids and IDs | done |
| 1 · Pipeline on real imagery | dataset builder; complete the labels; background chips; holdout; first GPU training; holdout evaluation; merge step; candidates → review | dataset builder done, labelling in progress, the rest open |
| 2 · Data engine | review loop with hard negatives; prefilter in production; comparison of boxes, oriented boxes and segmentation; optionally a second method | planned |
| 3 · Scale and delivery | state-wide run for Lower Saxony; site register with provenance | planned |
| 4 · Vision | stock monitoring on confirmed sites (§9) | not committed |

## 8. Risks and caveats

| Risk | Mitigation |
|---|---|
| Labels, imagery and reality drift apart (wood moves) | every label is tied to its image; the product is "sites with logyard activity at the flight date" |
| Confusable objects (gravel, compost, scrap, containers) | deliberate hard-negative collection |
| Misses propagate through the cascade | permissive early stages; human review as final filter |
| Random train/validation splits leak spatial information | spatial split; frozen holdout of whole sites |
| Few labels, spread over twelve states with different imagery | train across states; report per state; add labels in the target state |
| No contiguous fully labelled area yet | background chips first; a fully reviewed pilot region later |
| Large yards split at chip borders | fragment-joining merge; overlap is a parameter |
| Training and prediction pixels differ | pixel comparison; if needed, same source for both |
| State image services are down at times | resumable fetch; the archive is frozen once fetched |
| Framework licence | see §6 |

## 9. Future vision

Once site detection is reliable, confirmed sites become a watch list. Satellite time series
(for example Sentinel-2: 10 m, about 5-day revisit) cannot show individual logs but can show
*change* on a known yard footprint. Aerial imagery finds and outlines sites at high
resolution and low frequency; satellites could monitor them at low resolution and high
frequency.

## 10. Glossary

- **DOP20** – digital orthophotos with 20 cm ground resolution, produced by the state survey
  agencies; flights repeat every 2–3 years.
- **Polygon** – drawn by hand in QGIS; the ground truth.
- **Tile / chip** – a tile is how imagery is stored; a chip is what the model sees (§5).
- **Label** – a box in the model's file format, derived from the polygons per chip.
- **Background chip** – a chip without labels; teaches the model that "nothing here" is valid.
- **Hard negative** – a non-target that looks like the target; the strongest lever against false alarms.
- **Validation vs. holdout** – validation is used to choose during development; the holdout is
  only used to measure.
- **Spatial holdout** – a test set separated by geography, not by random choice. Neighbouring
  chips share landscape, flight and light, so random splits flatter the scores.
- **Recall / precision** – share of real objects found / share of detections that are real.
- **IoS (intersection over smaller)** – overlap divided by the smaller box; the measure for
  joining two halves of one yard cut at a chip border.
- **COG** – a GeoTIFF laid out so that windows can be read over the network without
  downloading the file.
- **STAC** – a standard catalogue of images searchable by place and time.
- **WMS** – a web service that renders any requested map rectangle as an image.
- **Manifest** – the table recording for every archived tile where and when it came from and
  its checksum.
