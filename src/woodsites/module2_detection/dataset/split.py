"""Spatial train/val split (Module 2 internal; the holdout is separate and never written).

Label chips that overlap each other form a group (a site with its neighbours). Whole groups
go to val until at least val_share of the label chips are there, so no val chip ever
overlaps a train chip. Background chips: val_share of them to val. Seeded.
"""
from __future__ import annotations

import math
import random

from woodsites.core.grid import chips_overlap


def groups(chips: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    parent = {c: c for c in chips}

    def find(c):
        while parent[c] != c:
            parent[c] = parent[parent[c]]
            c = parent[c]
        return c

    s = set(chips)
    for c in chips:
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                n = (c[0] + di, c[1] + dj)
                if n in s and chips_overlap(c, n):
                    ra, rb = find(c), find(n)
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)
    out: dict = {}
    for c in chips:
        out.setdefault(find(c), []).append(c)
    return sorted((sorted(g) for g in out.values()), key=lambda g: g[0])


def pick_val_groups(gs: list[list], target: float) -> list[list]:
    """Whole groups whose chip count is as close as possible to target (subset sum over the
    group sizes; groups are already in seeded random order, the first fitting combination wins).
    At least one group always stays in train; nothing goes to val if there is only one group."""
    if len(gs) < 2 or target <= 0:
        return []
    total = sum(len(g) for g in gs)
    reach: dict[int, list[int]] = {0: []}          # chip count -> indices of the groups used
    for k, g in enumerate(gs):
        for s, used in list(reach.items()):
            t = s + len(g)
            if t not in reach and t < total:       # never all groups
                reach[t] = used + [k]
    best = min((s for s in reach if s > 0), key=lambda s: (abs(s - target), s < target), default=0)
    return [gs[k] for k in reach.get(best, [])]


def split(label_chips: list[tuple[int, int]], background: list[tuple[int, int]],
          val_share: float, seed: int) -> dict[tuple[int, int], str]:
    rng = random.Random(seed)
    out = {c: "train" for c in label_chips + background}
    gs = groups(sorted(label_chips))
    rng.shuffle(gs)
    target = val_share * len(label_chips)
    for g in pick_val_groups(gs, target):
        for c in g:
            out[c] = "val"
    bg = sorted(background)
    rng.shuffle(bg)
    for c in bg[:math.ceil(val_share * len(bg))] if len(bg) > 1 else []:
        out[c] = "val"
    return out
