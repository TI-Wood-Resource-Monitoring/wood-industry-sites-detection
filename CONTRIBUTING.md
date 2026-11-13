# Working on this repository

## Before you start
1. Clone the repository and copy `configs/config.example.toml` to `configs/config.toml`;
   fill in the paths to the data on your computer.
2. Run the tests (OSGeo4W Shell, in the repository folder): `python tests\test_tile_and_chip.py`
   – must end with `ALL PASS`.

## Rules
- **No data in git.** Polygons, imagery, datasets, model weights, QGIS projects and results
  stay outside the repository (see `.gitignore`). Check `git status` before every commit.
- **No personal or internal information.** No names, e-mail addresses, internal paths or
  real coordinates in code, comments or documentation – this repository is public.
- **One task, one branch.** Create a branch per issue (`feature/postprocess-merge`,
  `fix/edge-tiles`), open a pull request into `main`, let someone else look at it.
- **Tests stay green.** Run the tests before you push; add a test for every new rule.
- **Contracts first.** If a file passed between modules changes (see `docs/contracts/`), update the
  contract description in the same pull request.
- **Small commits, clear messages:** `fix: ...`, `feat: ...`, `docs: ...`, `refactor: ...`.
