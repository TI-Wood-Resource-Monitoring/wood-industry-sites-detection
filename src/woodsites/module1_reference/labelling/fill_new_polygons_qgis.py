r"""
fill_new_polygons_qgis.py - fill in the attributes of newly drawn polygons, inside QGIS.

In the QGIS Python console (paste this ONE line, the file can be run again any time):

exec(open(r"<repo>\src\woodsites\module1_reference\labelling\fill_new_polygons_qgis.py", encoding="utf-8").read())

For every polygon of layer dop20_polygons with an empty new_id, site_id or land:
  site_id, land  <- from the industry_site outline the polygon lies in (largest overlap);
                    outside every industry outline: from the nearest polygon with a site_id
  category       <- holz_klein, if empty      (empty = "not set because it is holz_klein")
  triage_note    <- typ=rundholz, if empty    (empty = "not set because it is rundholz")
                    ("typ=..." typed into the field triage by mistake is moved to triage_note)
  herkunft       <- dop20_neu
  new_id         <- kept if already typed, otherwise <site>_N<next number>
                    (continuing after the highest N of that site, in the order they were drawn)

Nothing is saved: the values go into the edit buffer. Look at the printed table (and the
attribute table), then "Save Layer Edits" and Ctrl+S. To undo instead: Toggle Editing -> discard.
Lines marked CHECK need a look: another site is about as close, or a typed new_id does not
match the site found.
"""
import re

from qgis.core import QgsProject


def _empty(v):
    return v is None or str(v).strip() in ("", "NULL")


def _fill_new_polygons():
    lyrs = [l for l in QgsProject.instance().mapLayers().values()
            if "dop20_polygons.gpkg" in l.source() and "layername=dop20_polygons" in l.source()]
    if not lyrs:
        print("layer dop20_polygons (from dop20_polygons.gpkg) is not in this project")
        return
    lyr = lyrs[0]
    need = ("new_id", "site_id", "land", "category", "triage", "triage_note", "herkunft")
    idx = {n: lyr.fields().indexOf(n) for n in need}
    missing = [n for n, i in idx.items() if i < 0]
    if missing:
        print("fields missing in dop20_polygons: " + ", ".join(missing))
        return
    feats = list(lyr.getFeatures())
    known = [f for f in feats if not _empty(f["site_id"]) and not _empty(f["land"]) and f.hasGeometry()]
    industry = [f for f in known if str(f["category"]) == "industry_site"]
    todo = sorted([f for f in feats if _empty(f["new_id"]) or _empty(f["site_id"]) or _empty(f["land"])],
                  key=lambda f: f.id())
    if not todo:
        print("no polygon with an empty new_id, site_id or land - nothing to do")
        return
    used = {str(f["new_id"]) for f in feats if not _empty(f["new_id"])}
    if not lyr.isEditable():
        lyr.startEditing()
    print(f"{'fid':>5}  {'new_id':10s} {'category':14s} {'triage_note':18s} site (how)")
    n_done = 0
    for f in todo:
        if not f.hasGeometry():
            print(f"{f.id():5d}  skipped: no geometry")
            continue
        g = f.geometry()
        checks = []
        hits = sorted(((g.intersection(k.geometry()).area(), str(k["site_id"]), str(k["land"]), str(k["new_id"]))
                       for k in industry if g.intersects(k.geometry())), reverse=True)
        hits = [h for h in hits if h[0] > 0]
        if hits:
            _, site, land, inside = hits[0]
            how = f"inside {inside}"
            if len({h[1] for h in hits}) > 1:
                checks.append("also overlaps " + ", ".join(sorted({h[3] for h in hits[1:]})))
        else:
            near = sorted((g.distance(k.geometry()), str(k["site_id"]), str(k["land"]))
                          for k in known if k.id() != f.id())
            d, site, land = near[0]
            how = f"nearest, {d:.0f} m"
            other = sorted({s for dd, s, _ in near if s != site and dd < d + 300})
            if other:
                checks.append(", ".join(other) + " also close")
        if _empty(f["new_id"]):
            n = max([int(m.group(1)) for u in used if (m := re.match(rf"^{re.escape(site)}_N(\d+)$", u))],
                    default=0) + 1
            new_id = f"{site}_N{n:02d}"
            used.add(new_id)
        else:
            new_id = str(f["new_id"])
            if not new_id.startswith(site + "_"):
                checks.append(f"typed new_id does not match {site}")
        cat = "holz_klein" if _empty(f["category"]) else str(f["category"])
        tri = "" if _empty(f["triage"]) else str(f["triage"]).strip()
        note = "" if _empty(f["triage_note"]) else str(f["triage_note"])
        if tri.lower().startswith("typ="):                  # typed into the wrong field
            note = tri if not note else note + "; " + tri
            lyr.changeAttributeValue(f.id(), idx["triage"], None)
            checks.append(f"moved '{tri}' from triage to triage_note")
        if not note:
            note = "typ=rundholz"
        for name, val in (("new_id", new_id), ("site_id", site), ("land", land), ("category", cat),
                          ("triage_note", note), ("herkunft", "dop20_neu")):
            lyr.changeAttributeValue(f.id(), idx[name], val)
        n_done += 1
        warn = f"   CHECK: {'; '.join(checks)}" if checks else ""
        print(f"{f.id():5d}  {new_id:10s} {cat:14s} {note:18s} {site} ({how}){warn}")
    lyr.triggerRepaint()
    print(f"\n{n_done} polygon(s) filled in the edit buffer. Check the table, then 'Save Layer Edits' and Ctrl+S.")


_fill_new_polygons()
