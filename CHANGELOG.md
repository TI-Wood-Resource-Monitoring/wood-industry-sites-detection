# Changelog

All notable changes to this project. Dates in ISO format.

## [Unreleased]
### Changed
- Code moved into one installable package `src/woodsites` with one subpackage per module
  (`core`, `module1_reference`, `module2_detection`, `module3_review`); the former
  `chipkit` package is split into `core` and `module2_detection/dataset`.
- Environment variable renamed: `LOGYARD_CONFIG` -> `WOODSITES_CONFIG`.
- All paths come from `configs/config.toml` (template `configs/config.example.toml`);
  no personal or internal paths in the code.
- `check_lgln_cog.py` / `check_lgln_stac.py`: output folder from `[paths] archive`,
  test point from the command line or `[checks] test_point`.
- Module boundary fixed: Module 1 (`module1_reference`) ends with the reference set (image
  archive + polygon files); Module 2 (`module2_detection`) builds the model-specific inputs.
  The image archive scripts moved into Module 1. New local `data/` folder (not committed).
