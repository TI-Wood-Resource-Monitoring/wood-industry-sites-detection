"""Reading the settings file.

The settings file is a small text file in the TOML format. It holds everything
that differs from computer to computer, above all the paths of the polygon
file and of the image archive. It is private and not part of the repository.

Normally it is configs/config.toml in the repository folder. On another
computer the variable WOODSITES_CONFIG can name a different file.

No script contains a path of its own. Every script asks this file.
"""

import os
import tomllib

# Name of the variable that can point to another settings file.
CONFIG_VARIABLE = "WOODSITES_CONFIG"

# Where the settings file is expected otherwise. The path has no drive letter,
# so it is looked for in the folder the script is started from. That is why
# every script is started from the repository folder.
DEFAULT_CONFIG_FILE = os.path.join("configs", "config.toml")


def config_file_path() -> str:
    """Say which settings file is to be used.

    Input:  nothing.
    Output: the path as text. It is the file named in the variable
            WOODSITES_CONFIG if that variable is set, otherwise
            configs/config.toml.

    This function only names the file. It does not open it and does not look
    whether it exists; read_config does that.
    """
    from_variable = os.environ.get(CONFIG_VARIABLE, "")
    # A variable that is set but empty counts as not set.
    if from_variable != "":
        return from_variable
    return DEFAULT_CONFIG_FILE


def read_config(path: str, needed_paths: list[str]) -> dict:
    """Read the settings file and make sure the needed paths are in it.

    Input:  path         - path of the settings file (from config_file_path).
            needed_paths - list of the names in the section [paths] that the
                           calling script cannot work without, for example
                           ["polygons_gpkg", "archive"].
    Output: dictionary with everything in the file, section by section. The
            archive path, for example, is result["paths"]["archive"].

    Stops with a short message if the file does not exist, cannot be read as
    TOML, or if one of the needed paths is missing or empty.
    """
    # The three problems below can only be solved by the person at the
    # keyboard, by correcting a file. So the program stops with a plain
    # sentence (SystemExit) instead of a long technical error report.
    if not os.path.isfile(path):
        raise SystemExit(
            f"settings file not found: {path}\n"
            f"Start the script from the repository folder, or set the variable "
            f"{CONFIG_VARIABLE} to the path of your settings file.")
    # "rb" opens the file as raw bytes; the TOML reader wants it that way.
    with open(path, "rb") as file:
        try:
            config = tomllib.load(file)
        except tomllib.TOMLDecodeError as error:
            raise SystemExit(f"{path} is not valid TOML: {error}")
    paths = config.get("paths", {})
    # Collect all missing names first, so that one run shows all of them.
    missing = []
    for name in needed_paths:
        if name not in paths or paths[name] == "":
            missing.append(name)
    if missing:
        raise SystemExit(
            f"{path}: missing or empty in the section [paths]: " + ", ".join(missing))
    return config
