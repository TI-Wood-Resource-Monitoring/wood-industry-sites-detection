"""config.toml: one file with all paths and parameters (laptop, GPU desktop, CODE-DE, cluster).

Looked up in this order: the file named in the environment variable WOODSITES_CONFIG,
then configs/config.toml in the repository (copy it from configs/config.example.toml).
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]          # src/woodsites/core/config.py -> repository
DEFAULT_CONFIG = REPO_ROOT / "configs" / "config.toml"

TC_DEFAULTS = {
    "holz_klein": "positive",     # positive | background | mask
    "min_visible": 0.5,           # share of a polygon inside the chip to keep its box
    "min_visible_m2": 10000.0,    # ... or this much visible area (1 ha), whatever the share
    "mask_value": 114,            # grey (RGB 114/114/114)
    "mask_grow_px": 2,            # mask grown by 2 px = 0.8 m
    "min_box_px": 4,              # boxes narrower than this are masked instead
    "max_mask_share": 0.25,       # chips with more grey than this are left out
    "max_empty_share": 0.01,      # chips with more white/black pixels than this are left out
    "chip_status_ok": ["vollständig"],
    "chip_status_unsure": ["unsicher"],
    "background_status_ok": ["ok"],
    "val_share": 0.15,
    "seed": 1,
    "image_format": "GTiff",
    "tile_cache": 16,             # decoded tiles kept in memory (12 MB each)
}
HOLZ_KLEIN_MODES = ("positive", "background", "mask")


class Config:
    def __init__(self, data: dict, path: Path):
        self.data, self.path = data, path
        self.paths = data.get("paths", {})
        self.tc = {**TC_DEFAULTS, **data.get("tile_and_chip", {})}
        if self.tc["holz_klein"] not in HOLZ_KLEIN_MODES:
            raise SystemExit(f"{path}: [tile_and_chip] holz_klein must be one of {HOLZ_KLEIN_MODES}")

    def path_of(self, key: str, required: bool = True) -> Path | None:
        v = (self.paths.get(key) or "").strip()
        if not v:
            if required:
                raise SystemExit(f"{self.path}: [paths] {key} is missing")
            return None
        return Path(v)


def config_path(path: str | Path | None = None) -> Path:
    """The config file to use: explicit path, else WOODSITES_CONFIG, else configs/config.toml."""
    return Path(path or os.environ.get("WOODSITES_CONFIG") or DEFAULT_CONFIG)


def load(path: str | Path | None = None) -> Config:
    p = config_path(path)
    if not p.exists():
        raise SystemExit(f"config file not found: {p}\n"
                         "Copy configs/config.example.toml to configs/config.toml and fill in the paths, "
                         "or set the environment variable WOODSITES_CONFIG to your config file.")
    with open(p, "rb") as f:
        return Config(tomllib.load(f), p)
