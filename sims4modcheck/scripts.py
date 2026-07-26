"""Checks for .ts4script mods (script mods).

A .ts4script is a plain ZIP archive containing a Python package.  The game
imports it directly from the archive, so the two things that break script
mods are a damaged archive and bytecode compiled for the wrong Python.
"""

from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass, field

# The Python the game ships.  Sims 4 moved from 3.3 to 3.7 in the November
# 2020 patch and has stayed there since; override with --python-version if
# EA ever moves again.
GAME_PYTHON = "3.7"
GAME_PYC_MAGICS = frozenset({3390, 3391, 3392, 3393, 3394})

# Bytecode magic -> Python release.  Ranges, because every alpha bumps it.
_MAGIC_RANGES: list[tuple[int, int, str]] = [
    (3000, 3230, "3.3 or older"),
    (3231, 3309, "3.3"),
    (3310, 3349, "3.4"),
    (3350, 3378, "3.5"),
    (3379, 3389, "3.6"),
    (3390, 3394, "3.7"),
    (3400, 3413, "3.8"),
    (3420, 3425, "3.9"),
    (3430, 3499, "3.10"),
    (3500, 3549, "3.11"),
    (3550, 3599, "3.12"),
    (3600, 3649, "3.13"),
    (3650, 3699, "3.14"),
]


def python_version_for_magic(magic: int) -> str:
    for low, high, name in _MAGIC_RANGES:
        if low <= magic <= high:
            return name
    return f"unknown (magic {magic})"


class ScriptError(Exception):
    """The archive cannot be read as a script mod."""


@dataclass
class ScriptMod:
    path: str
    file_size: int
    entry_count: int = 0
    py_files: int = 0
    pyc_files: int = 0
    # Python release -> how many .pyc files were built for it.
    pyc_versions: dict[str, int] = field(default_factory=dict)
    has_init: bool = False
    nested_archives: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)

    @property
    def wrong_version_pycs(self) -> dict[str, int]:
        return {v: n for v, n in self.pyc_versions.items() if v != GAME_PYTHON}


def read_script_mod(path: str, verify_data: bool = False) -> ScriptMod:
    """Inspect a .ts4script archive.

    Raises ScriptError if the file is not a usable ZIP.
    """
    import os

    size = os.path.getsize(path)
    if size == 0:
        raise ScriptError("file is empty (0 bytes)")

    if not zipfile.is_zipfile(path):
        with open(path, "rb") as fh:
            head = fh.read(8)
        if head.startswith(b"Rar!"):
            raise ScriptError("this is a RAR archive renamed to .ts4script -- unpack it")
        if head.startswith(b"7z\xbc\xaf"):
            raise ScriptError("this is a 7-Zip archive renamed to .ts4script -- unpack it")
        if head.startswith(b"DBPF"):
            raise ScriptError("this is a .package renamed to .ts4script -- rename it back")
        raise ScriptError("not a valid ZIP archive -- the download is corrupt")

    mod = ScriptMod(path=path, file_size=size)

    try:
        with zipfile.ZipFile(path) as zf:
            if verify_data:
                bad = zf.testzip()
                if bad is not None:
                    raise ScriptError(f"failed CRC check on '{bad}' -- the archive is damaged")

            names = zf.namelist()
            mod.entry_count = len(names)

            for name in names:
                lower = name.lower()
                if lower.endswith("/"):
                    continue
                if lower.endswith(".py"):
                    mod.py_files += 1
                elif lower.endswith((".pyc", ".pyo")):
                    mod.pyc_files += 1
                    version = _pyc_version(zf, name)
                    mod.pyc_versions[version] = mod.pyc_versions.get(version, 0) + 1
                elif lower.endswith((".zip", ".rar", ".7z", ".ts4script")):
                    mod.nested_archives.append(name)

                base = lower.rsplit("/", 1)[-1]
                if base in ("__init__.py", "__init__.pyc"):
                    mod.has_init = True
    except zipfile.BadZipFile as exc:
        raise ScriptError(f"the ZIP directory is damaged ({exc})") from exc

    if mod.py_files == 0 and mod.pyc_files == 0:
        raise ScriptError("contains no Python files -- the game has nothing to load")

    return mod


def _pyc_version(zf: zipfile.ZipFile, name: str) -> str:
    try:
        with zf.open(name) as fh:
            head = fh.read(4)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        return f"unreadable ({exc})"
    if len(head) < 4:
        return "unknown (file too short)"
    magic = struct.unpack("<H", head[:2])[0]
    if head[2:4] != b"\r\n":
        return f"unknown (magic {magic})"
    return python_version_for_magic(magic)
