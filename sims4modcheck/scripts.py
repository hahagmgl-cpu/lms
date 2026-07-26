"""Validator for .ts4script mods (script mods).

A .ts4script is a plain zip archive of compiled Python (.pyc). The game loads
it with its own bundled interpreter, so the bytecode has to match that
interpreter's version exactly -- a mod compiled for any other Python is dead
weight, and this is by far the most common reason a script mod "does nothing".
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field

# The Sims 4 has shipped Python 3.7 since the November 2020 patch. Before that
# it was 3.3, which is why so many pre-2020 script mods stopped working.
GAME_PYTHON_MAGIC = 3394
GAME_PYTHON_VERSION = "3.7"

# Enough of the table to name whatever a mod was actually built with.
_MAGIC_TO_VERSION = {
    3230: "3.3",
    3310: "3.4",
    3350: "3.5",
    3351: "3.5",
    3379: "3.6",
    3394: "3.7",
    3413: "3.8",
    3425: "3.9",
    3439: "3.10",
    3495: "3.11",
    3531: "3.12",
    3571: "3.13",
}


class ScriptError(Exception):
    """The file is not a usable script archive."""


@dataclass
class ScriptMod:
    path: str
    pyc_count: int = 0
    py_source_count: int = 0
    # Bytecode magic number -> how many .pyc files use it.
    magics: dict[int, int] = field(default_factory=dict)

    @property
    def bad_magics(self) -> dict[int, int]:
        return {m: n for m, n in self.magics.items() if m != GAME_PYTHON_MAGIC}


def version_for_magic(magic: int) -> str:
    return _MAGIC_TO_VERSION.get(magic, f"unknown (magic {magic})")


def read_script_mod(path: str) -> ScriptMod:
    """Inspect a .ts4script archive.

    Raises ScriptError if the archive cannot be opened or is not a zip.
    """
    mod = ScriptMod(path=path)
    try:
        with zipfile.ZipFile(path) as zf:
            broken = zf.testzip()
            if broken is not None:
                raise ScriptError(f"archive is corrupt: {broken} failed its CRC check")
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename.lower()
                if name.endswith(".py"):
                    mod.py_source_count += 1
                elif name.endswith(".pyc"):
                    mod.pyc_count += 1
                    magic = _read_magic(zf, info)
                    if magic is not None:
                        mod.magics[magic] = mod.magics.get(magic, 0) + 1
    except zipfile.BadZipFile as exc:
        raise ScriptError(f"not a valid zip archive: {exc}") from None
    except OSError as exc:
        raise ScriptError(f"could not be read: {exc}") from None
    return mod


def _read_magic(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> int | None:
    with zf.open(info) as fh:
        head = fh.read(4)
    if len(head) < 4:
        return None
    return int.from_bytes(head[:2], "little")
