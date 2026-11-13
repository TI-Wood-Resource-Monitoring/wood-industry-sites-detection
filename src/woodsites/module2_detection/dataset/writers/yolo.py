"""YOLO (Ultralytics) dataset layout - the only file in woodsites that knows YOLO.

  images/<split>/<chip_id>.tif     labels/<split>/<chip_id>.txt     data.yaml
Label line: "class x_centre y_centre width height", normalised 0..1, y counted from the TOP.
A chip without labels gets an empty .txt (background for YOLO).
"""
from __future__ import annotations

from pathlib import Path

from woodsites.core import grid

CLASSES = {0: "logyard"}
CATEGORY_CLASS = {"logyard_rough": 0, "holz_klein": 0}     # holz_klein "positive" = logyard


def image_path(root: Path, split: str, cid: str, ext: str = ".tif") -> Path:
    return root / "images" / split / f"{cid}{ext}"


def label_path(root: Path, split: str, cid: str) -> Path:
    return root / "labels" / split / f"{cid}.txt"


def label_lines(boxes, i: int, j: int) -> list[str]:
    out = []
    for b in boxes:
        xc, yc, w, h = grid.box_to_yolo(b.minx, b.miny, b.maxx, b.maxy, i, j)
        out.append(f"{CATEGORY_CLASS[b.category]} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")
    return out


def write_labels(root: Path, split: str, cid: str, lines: list[str]) -> None:
    p = label_path(root, split, cid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def read_labels(root: Path, split: str, cid: str) -> list[tuple[int, float, float, float, float]]:
    out = []
    for line in label_path(root, split, cid).read_text(encoding="utf-8").splitlines():
        if line.strip():
            c, *v = line.split()
            out.append((int(c), *map(float, v)))
    return out


def write_data_yaml(root: Path, final_root: Path) -> None:
    """final_root = the folder name after the run (the dataset is built in <name>.part)."""
    txt = (f"# YOLO dataset written by tile_and_chip.py. On another computer change `path`.\n"
           f"path: {final_root.resolve().as_posix()}\n"
           f"train: images/train\nval: images/val\n"
           f"names:\n" + "".join(f"  {k}: {v}\n" for k, v in CLASSES.items()))
    (root / "data.yaml").write_text(txt, encoding="utf-8")
