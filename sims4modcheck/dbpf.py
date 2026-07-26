"""Reader/validator for DBPF v2.1 packages (the format used by The Sims 4).

Only the header and the resource index are parsed. That is enough to tell a
healthy package from a broken one and to list the resource keys a package
provides, which is what conflict detection needs. Resource *contents* are never
decompressed -- scanning a 40 GB Mods folder has to stay fast.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER_SIZE = 96
MAGIC = b"DBPF"

# The Sims 4 ships packages as DBPF 2.1. Sims 2 (1.x) and Sims 3 (2.0) packages
# are a common source of "why isn't my mod working" -- the game silently
# ignores them.
TS4_VERSION = (2, 1)

# Offsets inside the 96 byte header.
_OFF_MAJOR = 4
_OFF_MINOR = 8
_OFF_INDEX_COUNT = 36
_OFF_INDEX_SIZE = 44
_OFF_INDEX_OFFSET = 64

# Index entries never exceed 32 bytes, so this bounds how much we trust the
# header's entry count before declaring the index corrupt.
_MIN_ENTRY_SIZE = 16


class DBPFError(Exception):
    """The file is not a package we can read."""


@dataclass(frozen=True)
class ResourceKey:
    """A TGI key: the address of one resource inside a package."""

    type: int
    group: int
    instance: int

    def __str__(self) -> str:
        return f"{self.type:08X}:{self.group:08X}:{self.instance:016X}"


@dataclass
class Package:
    path: str
    major: int
    minor: int
    keys: list[ResourceKey]

    @property
    def is_ts4(self) -> bool:
        return (self.major, self.minor) == TS4_VERSION


def read_package(path: str, *, read_index: bool = True) -> Package:
    """Parse `path` as a DBPF package.

    Raises DBPFError with a human-readable reason if the file cannot be read as
    one. With read_index=False only the header is validated.
    """
    with open(path, "rb") as fh:
        header = fh.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE:
            if not header:
                raise DBPFError("file is empty (0 bytes)")
            raise DBPFError(
                f"file is truncated: {len(header)} bytes, a package header needs {HEADER_SIZE}"
            )
        if header[:4] != MAGIC:
            raise DBPFError(
                "missing DBPF signature -- this is not a package file "
                f"(starts with {header[:4]!r})"
            )

        major = _u32(header, _OFF_MAJOR)
        minor = _u32(header, _OFF_MINOR)
        count = _u32(header, _OFF_INDEX_COUNT)
        index_size = _u32(header, _OFF_INDEX_SIZE)
        index_offset = _u32(header, _OFF_INDEX_OFFSET)

        keys: list[ResourceKey] = []
        if read_index and count:
            keys = _read_index(fh, path, count, index_offset, index_size)

    return Package(path=path, major=major, minor=minor, keys=keys)


def _read_index(
    fh, path: str, count: int, offset: int, size: int
) -> list[ResourceKey]:
    file_size = _file_size(fh)
    if offset == 0 or offset >= file_size:
        raise DBPFError(
            f"resource index points outside the file (offset {offset}, file is {file_size} bytes)"
        )
    if count * _MIN_ENTRY_SIZE > file_size:
        raise DBPFError(
            f"header claims {count} resources, too many for a {file_size} byte file"
        )

    fh.seek(offset)
    blob = fh.read(size if size else file_size - offset)
    if len(blob) < 4:
        raise DBPFError("resource index is truncated")

    flags = _u32(blob, 0)
    if flags > 0xF:
        raise DBPFError(f"unrecognised index flags 0x{flags:X}; index is corrupt")

    # A set flag means that field is stored once, up front, instead of per
    # entry. The order of the constants matches the order of the fields.
    pos = 4
    constants: dict[int, int] = {}
    for bit in range(4):
        if flags & (1 << bit):
            if pos + 4 > len(blob):
                raise DBPFError("resource index is truncated (constant header)")
            constants[bit] = _u32(blob, pos)
            pos += 4

    variable = 4 - len(constants)
    entry_size = variable * 4 + 16
    needed = pos + count * entry_size
    if needed > len(blob):
        raise DBPFError(
            f"resource index is truncated: need {needed} bytes, have {len(blob)}"
        )

    keys: list[ResourceKey] = []
    for _ in range(count):
        fields: list[int] = []
        for bit in range(4):
            if bit in constants:
                fields.append(constants[bit])
            else:
                fields.append(_u32(blob, pos))
                pos += 4
        # Skip position, filesize, memsize, compression type and commit flag.
        pos += 16
        type_id, group, inst_hi, inst_lo = fields
        keys.append(
            ResourceKey(type=type_id, group=group, instance=(inst_hi << 32) | inst_lo)
        )
    return keys


def _u32(buf: bytes, offset: int) -> int:
    return struct.unpack_from("<I", buf, offset)[0]


def _file_size(fh) -> int:
    here = fh.tell()
    fh.seek(0, 2)
    size = fh.tell()
    fh.seek(here)
    return size
