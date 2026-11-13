"""
tile_and_chip.py - polygons + frozen tile archive -> chips (2048 x 2048 px at 0.4 m) and labels.

Runs in the OSGeo4W Shell (Python + GDAL + numpy), no QGIS needed. Paths and parameters come
from configs/config.toml (or the file named in WOODSITES_CONFIG).

    cd /d <repo>          (then: python src\\woodsites\\module2_detection\\dataset\\tile_and_chip.py ...)
    python tile_and_chip.py check              check polygons, chip_check, tiles, background (writes nothing)
    python tile_and_chip.py sync-chipcheck     add plan chips that are missing in chip_check (status empty)
    python tile_and_chip.py train --dry-run    what a training run would do, without reading images
    python tile_and_chip.py train              build dataset d00N_<date> in dataset_root
    python tile_and_chip.py chips --chips <chip_id>,<chip_id>     prediction mode
    python tile_and_chip.py roundtrip d001_2026-11-02    YOLO boxes back to map coordinates

train options: --holz-klein positive|background|mask   --include-unsicher   --limit N (first N chips, test)
chips options: --chips id,id,...  or  --area file.gpkg  or  --bbox minx,miny,maxx,maxy   [--out folder]

Training chips: every chip of the plan (triage A/B or herkunft = dop20_neu) whose chip_check
status is "vollständig", plus background chips with status "ok". Labels at chip borders:
box if >= 50 % of the polygon or >= 1 ha is visible, otherwise the visible part is greyed out.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
import time
from pathlib import Path

# Find the repository's src/ folder so that `import woodsites` works without installing it.
for _p in Path(__file__).resolve().parents:
    if (_p / "src" / "woodsites").is_dir():
        sys.path.insert(0, str(_p / "src"))
        break

from woodsites.core import config as C, grid, polygons as P            # noqa: E402
from woodsites.core.sources import ArchiveSource, MissingTiles         # noqa: E402
from woodsites.module2_detection.dataset import index as I, labels as L  # noqa: E402
from woodsites.module2_detection.dataset import raster as R, split as S  # noqa: E402
from woodsites.module2_detection.dataset.writers import yolo as Y        # noqa: E402

import woodsites                                        # noqa: E402
LIB = Path(woodsites.__file__).resolve().parent


def hr(title: str) -> None:
    print(f"\n== {title} " + "=" * max(0, 70 - len(title)))


def touches_holdout(i: int, j: int, holdout: list) -> bool:
    if not holdout:
        return False
    b = P.box(*grid.chip_bounds(i, j))
    return any(g.Intersects(b) for g in holdout)


# =========================================================================
# check
# =========================================================================
def cmd_check(cfg: C.Config) -> int:
    tc = cfg.tc
    gpkg = cfg.path_of("polygons_gpkg")
    polys = P.read_polygons(gpkg)
    errors, warns = P.validate(polys)

    hr("polygons")
    cats: dict = {}
    for p in polys:
        k = (p.category or "-", "label" if p.is_label else ("plan" if p.in_plan else "ignored"))
        cats[k] = cats.get(k, 0) + 1
    for (cat, use), n in sorted(cats.items()):
        print(f"  {cat:15s} {use:8s} {n:4d}")
    print(f"  holz_klein is used as: {tc['holz_klein']}")

    hr("chips of the plan vs chip_check")
    plan = P.plan_chips(polys)
    status, bad = P.read_chip_status(gpkg)
    errors += bad
    missing = sorted(set(plan) - set(status))
    stale = sorted(set(status) - set(plan))
    counts: dict = {}
    for c in plan:
        s = status.get(c, "(not in chip_check)") or "(empty)"
        counts[s] = counts.get(s, 0) + 1
    print(f"  {len(plan)} chips in the plan, {len(status)} rows in chip_check")
    for s, n in sorted(counts.items()):
        print(f"    status {s:22s} {n:4d}")
    for c in missing:
        warns.append(f"chip {grid.chip_id(*c)} ({grid.old_chip_id(*c)}, {';'.join(sorted(plan[c]['sites']))}) "
                     "is in the plan but not in chip_check -> python tile_and_chip.py sync-chipcheck")
    for c in stale:
        warns.append(f"chip_check row {grid.old_chip_id(*c)} is not in the plan any more (no polygon of the plan touches it)")

    hr("tiles")
    src = ArchiveSource(cfg.path_of("archive"), tc["tile_cache"])
    for t in sorted(set(src.duplicates)):
        errors.append(f"manifest.csv lists {t} more than once")
    no_tiles = {c: src.missing_tiles(*c) for c in plan}
    no_tiles = {c: v for c, v in no_tiles.items() if v}
    print(f"  manifest: {len(src.rows)} tiles; plan chips with missing tiles: {len(no_tiles)}")
    for c, v in sorted(no_tiles.items()):
        warns.append(f"chip {grid.chip_id(*c)} ({';'.join(sorted(plan[c]['sites']))}): {len(v)} tile(s) missing, "
                     f"e.g. {v[0]} -> fetch_wms_chips.py plan + run")

    hr("labels at chip borders")
    lab = [p for p in polys if p.is_label]
    lost = []
    for p in lab:
        share, area = L.best_visibility(p, tc)
        if share < tc["min_visible"] and area < tc["min_visible_m2"]:
            lost.append(p.new_id)
            warns.append(f"{p.new_id}: never >= {tc['min_visible']:.0%} or >= {tc['min_visible_m2']:.0f} m2 in any chip "
                         "-> masked everywhere, never a label")
    print(f"  {len(lab)} label polygons, {len(lab) - len(lost)} get a box in at least one chip")

    hr("background and holdout")
    bgp = cfg.path_of("background_gpkg", required=False)
    bg = P.read_background(bgp)
    bcount: dict = {}
    for b in bg:
        bcount[b["status"] or "(empty)"] = bcount.get(b["status"] or "(empty)", 0) + 1
    print(f"  background chips: {len(bg)} {bcount if bg else '(run fetch_wms_chips.py background)'}")
    for b in bg:
        if b["status"] in tc["background_status_ok"] and src.missing_tiles(b["i"], b["j"]):
            warns.append(f"background chip {b['id']}: tiles missing")
    hp = cfg.path_of("holdout_gpkg", required=False)
    holdout = P.read_holdout(hp)
    print(f"  holdout: {hp if hp else 'none yet'} ({len(holdout)} geometries)")

    ready = [c for c in plan if status.get(c) in tc["chip_status_ok"] and c not in no_tiles
             and not touches_holdout(*c, holdout)]
    hr("summary")
    print(f"  training-ready now: {len(ready)} label chips, "
          f"{sum(1 for b in bg if b['status'] in tc['background_status_ok'])} background chips")
    for w in warns:
        print("  warning: " + w)
    for e in errors:
        print("  ERROR:   " + e)
    print(f"\n{len(errors)} error(s), {len(warns)} warning(s)")
    return 1 if errors else 0


# =========================================================================
# sync-chipcheck
# =========================================================================
def cmd_sync(cfg: C.Config) -> int:
    gpkg = cfg.path_of("polygons_gpkg")
    polys = P.read_polygons(gpkg)
    plan = P.plan_chips(polys)
    status, bad = P.read_chip_status(gpkg)
    if bad:
        print("\n".join("ERROR: " + b for b in bad))
        return 1
    missing = sorted(set(plan) - set(status))
    if not missing:
        print("chip_check already has every chip of the plan - nothing to add.")
        return 0
    rows = [(i, j, ";".join(sorted(plan[(i, j)]["lands"])), ";".join(sorted(plan[(i, j)]["sites"])))
            for i, j in missing]
    try:
        P.append_chip_rows(gpkg, rows)
    except RuntimeError as e:
        print(f"cannot write chip_check: {e}\nStop editing the layer in QGIS (save or discard), then run again.")
        return 1
    for i, j, land, sites in rows:
        print(f"  added {grid.old_chip_id(i, j)}  (= {grid.chip_id(i, j)})  {land}  {sites}")
    print(f"{len(rows)} chip(s) added with an empty status. In QGIS: reload the layer if they don't show.")
    return 0


# =========================================================================
# train
# =========================================================================
def next_dataset_name(root: Path) -> str:
    nums = [int(m.group(1)) for p in (root.iterdir() if root.exists() else [])
            if (m := re.match(r"d(\d{3})_", p.name))]
    return f"d{max(nums, default=0) + 1:03d}_{dt.date.today().isoformat()}"


def code_hash() -> str:
    import hashlib
    h = hashlib.sha256()
    for p in [Path(__file__).resolve()] + sorted(LIB.rglob("*.py")):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def cmd_train(cfg: C.Config, a: argparse.Namespace) -> int:
    t_start = time.monotonic()
    tc = dict(cfg.tc)
    if a.holz_klein:
        tc["holz_klein"] = a.holz_klein
    gpkg = cfg.path_of("polygons_gpkg")
    polys = P.read_polygons(gpkg)
    errors, warns = P.validate(polys)
    if errors:
        print("\n".join("ERROR: " + e for e in errors))
        print("fix these first (python tile_and_chip.py check shows everything)")
        return 1
    ok_status = set(tc["chip_status_ok"]) | (set(tc["chip_status_unsure"]) if a.include_unsicher else set())
    plan = P.plan_chips(polys)
    status, bad = P.read_chip_status(gpkg)
    if bad:
        print("\n".join("ERROR: " + b for b in bad))
        return 1
    holdout_path = cfg.path_of("holdout_gpkg", required=False)
    holdout = P.read_holdout(holdout_path)
    src = ArchiveSource(cfg.path_of("archive"), tc["tile_cache"])
    if src.duplicates:
        print("ERROR: manifest.csv lists tiles twice: " + ", ".join(sorted(set(src.duplicates))[:5]))
        return 1
    bg_path = cfg.path_of("background_gpkg", required=False)
    bg = P.read_background(bg_path)
    label_polys = [p for p in polys if p.is_label]

    skipped: list[dict] = []                 # chips left out before reading pixels
    label_cands, bg_cands = [], []
    for c in sorted(plan):
        s = status.get(c)
        reason = None
        if s is None:
            reason = "not in chip_check"
        elif s not in ok_status:
            reason = f"status '{s or 'empty'}'"
        elif touches_holdout(*c, holdout):
            reason = "holdout"
        if reason:
            skipped.append({"c": c, "kind": "label", "reason": reason, "status": s or ""})
        else:
            label_cands.append(c)
    for b in bg:
        c = (b["i"], b["j"])
        reason = None
        if b["status"] not in tc["background_status_ok"]:
            reason = f"status '{b['status'] or 'empty'}'"
        elif touches_holdout(*c, holdout):
            reason = "holdout"
        elif any(grid.chips_overlap(c, p) for p in plan):
            reason = "overlaps a plan chip"
        if reason:
            skipped.append({"c": c, "kind": "background", "reason": reason, "status": b["status"]})
        else:
            bg_cands.append(c)
    if a.limit:
        label_cands, bg_cands = label_cands[:a.limit], bg_cands[:max(1, a.limit // 10)] if bg_cands else []
    splits = S.split(label_cands, bg_cands, tc["val_share"], tc["seed"])

    root = cfg.path_of("dataset_root")
    name = next_dataset_name(root)
    final = root / name
    work = root / (name + ".part")
    print(f"dataset {name}: {len(label_cands)} label chips, {len(bg_cands)} background chips "
          f"(val: {sum(1 for v in splits.values() if v == 'val')}), holz_klein = {tc['holz_klein']}")
    if a.dry_run:
        n_box = n_mask = 0
        for c in label_cands:
            bxs, mks = L.chip_labels(*c, label_polys, tc)
            n_box, n_mask = n_box + len(bxs), n_mask + len(mks)
        miss = [c for c in label_cands + bg_cands if src.missing_tiles(*c)]
        print(f"dry run: {n_box} boxes, {n_mask} masked pieces, {len(miss)} chip(s) with missing tiles")
        by_reason: dict = {}
        for s in skipped:
            by_reason.setdefault(f"{s['kind']}: {s['reason']}", []).append(grid.chip_id(*s["c"]))
        for reason, ids in sorted(by_reason.items()):
            print(f"  left out {len(ids):4d} chip(s), {reason}"
                  + ("" if reason.startswith("label: status") else "  -> " + ", ".join(ids[:8])
                     + (" ..." if len(ids) > 8 else "")))
        for c in miss:
            print(f"  left out {grid.chip_id(*c)}: missing tiles")
        n_val = sum(1 for c in label_cands if splits[c] == "val")
        if label_cands and not n_val:
            print("  note: no label chip in val - all ready chips overlap each other (one site). "
                  "Fine for a test; for training, mark chips of a second site first.")
        print("nothing written (--dry-run).")
        return 0

    work.mkdir(parents=True)
    # ---- snapshot of the inputs (before reading anything else) ----
    snap = work / "snapshot"
    P.snapshot_gpkg(gpkg, snap / gpkg.name)
    if bg_path and bg_path.exists():
        P.snapshot_gpkg(bg_path, snap / bg_path.name)
    if holdout_path:
        P.snapshot_gpkg(holdout_path, snap / holdout_path.name)
    shutil.copyfile(src.archive / "manifest.csv", snap / "manifest.csv")
    shutil.copyfile(cfg.path, snap / "config.toml")
    with open(snap / "sha256.txt", "w", encoding="utf-8") as f:
        for p in sorted(snap.iterdir()):
            if p.name != "sha256.txt":
                f.write(f"{P.sha256(p)}  {p.name}\n")

    chip_rows, label_rows, mask_rows = [], [], []
    for s in skipped:
        chip_rows.append(base_row(s["c"], s["kind"], "", s["status"]) | {"written": 0, "skip_reason": s["reason"],
                                                                         "sites": sites_of(plan, s["c"])})
    todo = sorted([(c, "label") for c in label_cands] + [(c, "background") for c in bg_cands])
    n_written = 0
    for k, (c, kind) in enumerate(todo, 1):
        i, j = c
        cid, sp = grid.chip_id(i, j), splits[c]
        row = base_row(c, kind, sp, status.get(c, "ok") if kind == "label" else "ok") | {"sites": sites_of(plan, c)}
        try:
            rgb, meta = src.read(i, j)
        except MissingTiles as e:
            chip_rows.append(row | {"written": 0, "skip_reason": f"missing tiles: {e}"})
            print(f"  [{k}/{len(todo)}] {cid} left out: missing tiles")
            continue
        boxes, masks = L.chip_labels(i, j, label_polys, tc)
        if kind == "background" and boxes:
            chip_rows.append(row | {"written": 0, "skip_reason": "polygon inside background chip"})
            continue
        st = R.stats(rgb)
        m = R.rasterize([mk.geom for mk in masks], i, j)
        share = R.apply_mask(rgb, m, tc["mask_value"])
        row |= st | {"mask_share": round(share, 5), "n_labels": len(boxes),
                     "n_cut": sum(b.cut_at_edge for b in boxes), "n_masked": len(masks),
                     "tiles": ";".join(meta["tiles"]), "lands": ";".join(meta["lands"]),
                     "bildflug": ";".join(meta["bildflug"])}
        reason = None
        if st["empty_share"] > tc["max_empty_share"]:
            reason = f"empty pixels {st['empty_share']:.1%}"
        elif share > tc["max_mask_share"]:
            reason = f"masked {share:.1%}"
        if reason:
            chip_rows.append(row | {"written": 0, "skip_reason": reason})
            print(f"  [{k}/{len(todo)}] {cid} left out: {reason}")
            continue
        R.write_geotiff(Y.image_path(work, sp, cid), rgb, i, j,
                        {"CHIP_ID": cid, "DATASET": name, "TILES": row["tiles"], "BILDFLUG": row["bildflug"]})
        lines = Y.label_lines(boxes, i, j)
        Y.write_labels(work, sp, cid, lines)
        chip_rows.append(row | {"written": 1})
        n_written += 1
        for n, b in enumerate(boxes):
            label_rows.append({"chip_id": cid, "split": sp, "line": n, "new_id": b.new_id, "category": b.category,
                               "class_id": Y.CATEGORY_CLASS[b.category], "visible": round(b.visible, 4),
                               "cut_at_edge": int(b.cut_at_edge), "geom": P.box(b.minx, b.miny, b.maxx, b.maxy)})
        for mk in masks:
            mask_rows.append({"chip_id": cid, "new_id": mk.new_id, "category": mk.category,
                              "visible": round(mk.visible, 4), "reason": mk.reason, "geom": mk.geom})
        print(f"  [{k}/{len(todo)}] {cid} {sp:5s} {kind:10s} boxes {len(boxes):2d} masked {len(masks)} "
              f"({(time.monotonic() - t_start) / 60:.1f} min)", flush=True)

    for r in chip_rows:
        r["geom"] = I.chip_geom(r["i"], r["j"])
    I.write_index(work / "chip_index.gpkg", chip_rows, label_rows, mask_rows)
    Y.write_data_yaml(work, final)
    written = [r for r in chip_rows if r.get("written")]
    params = {"dataset": name, "created": dt.datetime.now().isoformat(timespec="seconds"),
              "config": str(cfg.path), "tile_and_chip": tc, "include_unsicher": a.include_unsicher,
              "limit": a.limit, "code_sha256_16": code_hash(), "holdout": str(holdout_path or ""),
              "counts": {"written": len(written),
                         "train": sum(1 for r in written if r["split"] == "train"),
                         "val": sum(1 for r in written if r["split"] == "val"),
                         "background": sum(1 for r in written if r["kind"] == "background"),
                         "boxes": len(label_rows), "masked_pieces": len(mask_rows),
                         "left_out": len(chip_rows) - len(written)},
              "minutes": round((time.monotonic() - t_start) / 60, 1)}
    (work / "params.json").write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(work / "report.txt", "w", encoding="utf-8") as f:
        f.write(f"{name}\n{json.dumps(params['counts'], ensure_ascii=False)}\n\nleft out:\n")
        for r in sorted(chip_rows, key=lambda r: r["id"]):
            if not r.get("written"):
                f.write(f"  {r['id']}  {r['old_id']}  {r['kind']:10s} {r.get('sites', '')}: {r['skip_reason']}\n")
        f.write("\nwarnings from the polygon check:\n" + "".join(f"  {w}\n" for w in warns))
    work.rename(final)
    print(f"\n{final}\n  {json.dumps(params['counts'], ensure_ascii=False)}\n  report: {final / 'report.txt'}"
          f"\n  check: open chip_index.gpkg (layers labels, masks) over images\\*\\*.tif in QGIS"
          f"\n  then:  python tile_and_chip.py roundtrip {name}")
    return 0


def base_row(c: tuple[int, int], kind: str, sp: str, status: str) -> dict:
    return {"id": grid.chip_id(*c), "i": c[0], "j": c[1], "old_id": grid.old_chip_id(*c),
            "kind": kind, "split": sp, "status": status}


def sites_of(plan: dict, c: tuple[int, int]) -> str:
    return ";".join(sorted(plan[c]["sites"])) if c in plan else ""


# =========================================================================
# chips (prediction mode): same reading, no labels, no mask, no status filter
# =========================================================================
def chips_from_args(a: argparse.Namespace) -> list[tuple[int, int]]:
    if a.chips:
        return sorted({grid.parse_chip_id(s) for s in a.chips.split(",") if s.strip()})
    if a.bbox:
        minx, miny, maxx, maxy = map(float, a.bbox.split(","))
        return sorted(set(grid.chips_touching_envelope(minx, miny, maxx, maxy)))
    if a.area:
        from osgeo import ogr
        ds = ogr.Open(a.area, 0)
        out = set()
        for f in ds.GetLayer(0):
            g = f.GetGeometryRef()
            minx, maxx, miny, maxy = g.GetEnvelope()
            out |= {c for c in grid.chips_touching_envelope(minx, miny, maxx, maxy)
                    if g.Intersects(P.box(*grid.chip_bounds(*c)))}
        return sorted(out)
    raise SystemExit("chips needs --chips, --bbox or --area")


def iter_chips(chips: list[tuple[int, int]], src):
    """Prediction mode as a function for the detector: yields (chip_id, rgb, meta) or
    (chip_id, None, {'error': ...}). Nothing is written."""
    for i, j in chips:
        try:
            rgb, meta = src.read(i, j)
            yield grid.chip_id(i, j), rgb, meta | R.stats(rgb)
        except MissingTiles as e:
            yield grid.chip_id(i, j), None, {"error": f"missing tiles: {e}"}


def cmd_chips(cfg: C.Config, a: argparse.Namespace) -> int:
    chips = chips_from_args(a)
    src = ArchiveSource(cfg.path_of("archive"), cfg.tc["tile_cache"])
    root = cfg.path_of("dataset_root")
    out = Path(a.out) if a.out else root / f"chips_{dt.datetime.now():%Y-%m-%d_%H%M%S}"
    rows = []
    for k, (cid, rgb, meta) in enumerate(iter_chips(chips, src), 1):
        i, j = grid.parse_chip_id(cid)
        row = base_row((i, j), "predict", "", "") | {"geom": I.chip_geom(i, j)}
        if rgb is None:
            rows.append(row | {"written": 0, "skip_reason": meta["error"]})
            print(f"  [{k}/{len(chips)}] {cid}: {meta['error']}")
            continue
        R.write_geotiff(out / "images" / f"{cid}.tif", rgb, i, j, {"CHIP_ID": cid, "TILES": ";".join(meta["tiles"])})
        rows.append(row | {k2: meta[k2] for k2 in ("empty_share", "mean_r", "mean_g", "mean_b",
                                                     "std_r", "std_g", "std_b")}
                    | {"tiles": ";".join(meta["tiles"]), "lands": ";".join(meta["lands"]),
                       "bildflug": ";".join(meta["bildflug"]), "written": 1})
        print(f"  [{k}/{len(chips)}] {cid} written", flush=True)
    I.write_index(out / "chip_index.gpkg", rows, [], [])
    print(f"{sum(r.get('written', 0) for r in rows)} chip(s) -> {out}")
    return 0


# =========================================================================
# roundtrip
# =========================================================================
def cmd_roundtrip(cfg: C.Config, a: argparse.Namespace) -> int:
    ds_dir = Path(a.dataset)
    if not ds_dir.is_absolute() and not ds_dir.exists():
        ds_dir = cfg.path_of("dataset_root") / a.dataset
    idx = ds_dir / "chip_index.gpkg"
    labels = I.read_layer(idx, "labels")
    chips = {r["id"]: r for r in I.read_layer(idx, "chips") if r["written"]}
    worst, n, problems = 0.0, 0, []
    by_chip: dict = {}
    for r in labels:
        by_chip.setdefault(r["chip_id"], []).append(r)
    for cid, ch in sorted(chips.items()):
        i, j = grid.parse_chip_id(cid)
        lines = Y.read_labels(ds_dir, ch["split"], cid)
        rows = sorted(by_chip.get(cid, []), key=lambda r: r["line"])
        if len(lines) != len(rows):
            problems.append(f"{cid}: {len(lines)} lines in the .txt, {len(rows)} in the index")
            continue
        bx = grid.chip_bounds(i, j)
        for (cls, xc, yc, w, h), r in zip(lines, rows):
            back = grid.yolo_to_box(xc, yc, w, h, i, j)
            minx, maxx, miny, maxy = r["geom"].GetEnvelope()
            dev = max(abs(back[0] - minx), abs(back[1] - miny), abs(back[2] - maxx), abs(back[3] - maxy))
            worst, n = max(worst, dev), n + 1
            if dev > 0.1:
                problems.append(f"{cid} line {r['line']} ({r['new_id']}): {dev:.3f} m off")
            if not (bx[0] - 1e-6 <= minx and maxx <= bx[2] + 1e-6 and bx[1] - 1e-6 <= miny and maxy <= bx[3] + 1e-6):
                problems.append(f"{cid} line {r['line']}: box outside its chip")
            if not (0 <= xc - w / 2 + 1e-6 and xc + w / 2 <= 1 + 1e-6 and 0 <= yc - h / 2 + 1e-6 and yc + h / 2 <= 1 + 1e-6):
                problems.append(f"{cid} line {r['line']}: YOLO box outside 0..1")
    print(f"{n} boxes in {len(chips)} chips; largest deviation map -> YOLO -> map: {worst * 100:.2f} cm")
    for p in problems:
        print("  PROBLEM: " + p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


# =========================================================================
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check", "sync-chipcheck", "train", "chips", "roundtrip"])
    ap.add_argument("dataset", nargs="?", help="roundtrip: dataset folder or name")
    ap.add_argument("--holz-klein", choices=C.HOLZ_KLEIN_MODES)
    ap.add_argument("--include-unsicher", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--chips")
    ap.add_argument("--area")
    ap.add_argument("--bbox")
    ap.add_argument("--out")
    ap.add_argument("--config", help="other config.toml (default: WOODSITES_CONFIG, else configs/config.toml)")
    a = ap.parse_args(argv)
    cfg = C.load(a.config)
    print(f"config: {cfg.path}")
    if a.command == "check":
        return cmd_check(cfg)
    if a.command == "sync-chipcheck":
        return cmd_sync(cfg)
    if a.command == "train":
        return cmd_train(cfg, a)
    if a.command == "chips":
        return cmd_chips(cfg, a)
    if not a.dataset:
        raise SystemExit("roundtrip needs a dataset, e.g. python tile_and_chip.py roundtrip d001_2026-11-02")
    return cmd_roundtrip(cfg, a)


if __name__ == "__main__":
    sys.exit(main())
