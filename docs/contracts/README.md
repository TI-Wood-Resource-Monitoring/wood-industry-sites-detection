# File contracts between modules

The modules only talk to each other through files. Each file below has a fixed layout,
so any module can be replaced as long as it reads and writes these files the same way.
**Change a contract only together with every script that reads or writes it.**

| File | Written by | Read by | Description |
|---|---|---|---|
| `manifest.csv` | module1_reference (imagery) | module2_detection | [manifest.md](manifest.md) |
| `kandidaten_<lauf-id>.gpkg` | module2_detection (2b) | module3_review | [kandidaten.md](kandidaten.md) |
| `freigabe.csv` | module3_review | module2_detection (2b) | [freigabe.md](freigabe.md) |
| `pruefung.gpkg` | module3_review | site register, module1_reference (hard negatives) | [pruefung.md](pruefung.md) |

Status: `manifest.csv` is implemented; the others are drafts from the architecture diagram
and are fixed when their scripts are written.
