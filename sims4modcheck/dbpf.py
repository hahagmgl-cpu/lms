"""Minimal DBPF (.package) reader for The Sims 4.

Only what a health check needs: validate the header, walk the resource
index, and optionally verify that every record actually decompresses.

Layout reference (DBPF 2.0 as used by TS4):

    header, 96 bytes
      0x00  char[4]  magic "DBPF"
      0x04  uint32   major version   (2)
      0x08  uint32   minor version   (1)
      0x24  uint32   index entry count
      0x28  uint32   index offset (v1.0, usually 0 here)
      0x2C  uint32   index size in bytes
      0x3C  uint32   index minor version
      0x40  uint32   index offset (v2.0)

    index
      uint32 flags -- bits 0..3 mark type/group/instance-hi/instance-lo as
      constant for the whole index; each set bit is followed by one uint32
      holding that constant, and the field is then omitted per entry.

    entry
      the four key fields that were not hoisted into the header, then
      uint32 position, uint32 size, uint32 decompressed size.  If bit 31 of
      size is set, a uint16 compression type and uint16 committed flag
      follow.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from typing import BinaryIO

MAGIC = b"DBPF"
HEADER_SIZE = 96

# Compression types found in the index.
COMP_NONE = 0x0000
COMP_STREAMABLE = 0xFFFF  # uncompressed, but read in a stream
COMP_DELETED = 0xFFFE  # tombstone; the record holds no data
COMP_ZLIB = 0x5A42
COMP_REFPACK = 0xFFFE  # not distinguished from deleted in practice

UNCOMPRESSED = (COMP_NONE, COMP_STREAMABLE)


class PackageError(Exception):
    """The file is not a package we can read."""


@dataclass(frozen=True)
class ResourceKey:
    type: int
    group: int
    instance: int

    def __str__(self) -> str:
        return f"{self.type:08X}:{self.group:08X}:{self.instance:016X}"


@dataclass
class ResourceEntry:
    key: ResourceKey
    offset: int
    size: int
    decompressed_size: int
    compression: int

    @property
    def is_compressed(self) -> bool:
        return self.compression not in UNCOMPRESSED


@dataclass
class Package:
    path: str
    file_size: int
    major: int
    minor: int
    index_count: int
    entries: list[ResourceEntry] = field(default_factory=list)
    # Non-fatal oddities noticed while parsing.
    anomalies: list[str] = field(default_factory=list)

    @property
    def keys(self) -> list[ResourceKey]:
        return [e.key for e in self.entries]


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def read_package(path: str, verify_data: bool = False) -> Package:
    """Parse `path` as a DBPF package.

    Raises PackageError when the file cannot be read as a package at all --
    that is the "this mod is broken" signal.  Recoverable weirdness is
    collected in `Package.anomalies` instead.
    """
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        file_size = fh.tell()
        fh.seek(0)

        if file_size == 0:
            raise PackageError("file is empty (0 bytes)")
        if file_size < HEADER_SIZE:
            raise PackageError(
                f"file is truncated: {file_size} bytes, a package header alone "
                f"needs {HEADER_SIZE}"
            )

        header = fh.read(HEADER_SIZE)
        if header[:4] != MAGIC:
            raise PackageError(_describe_wrong_magic(header))

        major = _u32(header, 0x04)
        minor = _u32(header, 0x08)
        if major != 2:
            raise PackageError(
                f"DBPF version {major}.{minor} -- not a Sims 4 package "
                f"(Sims 4 uses 2.x; 1.x is Sims 2/3)"
            )

        index_count = _u32(header, 0x24)
        index_size = _u32(header, 0x2C)
        index_offset = _u32(header, 0x40) or _u32(header, 0x28)

        pkg = Package(
            path=path,
            file_size=file_size,
            major=major,
            minor=minor,
            index_count=index_count,
        )

        if index_count == 0:
            return pkg

        if index_offset == 0 or index_size == 0:
            raise PackageError(
                f"index is missing (header claims {index_count} resources)"
            )
        if index_offset + index_size > file_size:
            raise PackageError(
                f"index runs past the end of the file (needs {index_offset + index_size} "
                f"bytes, file is {file_size}) -- the download is incomplete or corrupt"
            )

        fh.seek(index_offset)
        index = fh.read(index_size)
        if len(index) != index_size:
            raise PackageError("could not read the whole resource index")

        pkg.entries = _parse_index(index, index_count)

        for entry in pkg.entries:
            if entry.compression == COMP_DELETED:
                continue
            if entry.offset + entry.size > file_size:
                raise PackageError(
                    f"resource {entry.key} points past the end of the file "
                    f"-- the file is truncated or corrupt"
                )

        if verify_data:
            _verify_entries(fh, pkg)

    return pkg


def _describe_wrong_magic(header: bytes) -> str:
    """Turn a bad magic number into something a mod user can act on."""
    sigs = [
        (b"PK\x03\x04", "a ZIP archive renamed to .package -- extract it instead"),
        (b"Rar!", "a RAR archive renamed to .package -- extract it instead"),
        (b"7z\xbc\xaf", "a 7-Zip archive renamed to .package -- extract it instead"),
        (b"\x89PNG", "a PNG image renamed to .package"),
        (b"\xff\xd8\xff", "a JPEG image renamed to .package"),
        (b"%PDF", "a PDF renamed to .package"),
        (b"<!DOC", "an HTML page -- the download failed and saved the web page"),
        (b"<html", "an HTML page -- the download failed and saved the web page"),
        (b"DBPP", "a DBPP file, not a package"),
    ]
    for sig, why in sigs:
        if header.startswith(sig):
            return f"not a package: {why}"
    head = header[:4]
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in head)
    return (
        f"not a package: expected 'DBPF' at the start of the file, found "
        f"{printable!r} ({head.hex()})"
    )


def _parse_index(index: bytes, count: int) -> list[ResourceEntry]:
    flags = _u32(index, 0)
    pos = 4

    constants: dict[int, int] = {}
    for bit in range(4):
        if flags & (1 << bit):
            if pos + 4 > len(index):
                raise PackageError("resource index header is truncated")
            constants[bit] = _u32(index, pos)
            pos += 4

    entries: list[ResourceEntry] = []
    for i in range(count):
        fields = []
        for bit in range(4):
            if bit in constants:
                fields.append(constants[bit])
            else:
                if pos + 4 > len(index):
                    raise PackageError(
                        f"resource index is truncated at entry {i} of {count}"
                    )
                fields.append(_u32(index, pos))
                pos += 4

        if pos + 12 > len(index):
            raise PackageError(f"resource index is truncated at entry {i} of {count}")
        offset, raw_size, decompressed = struct.unpack_from("<III", index, pos)
        pos += 12

        if raw_size & 0x80000000:
            if pos + 4 > len(index):
                raise PackageError(
                    f"resource index is truncated at entry {i} of {count}"
                )
            compression, _committed = struct.unpack_from("<HH", index, pos)
            pos += 4
        else:
            compression = COMP_NONE

        type_id, group_id, inst_hi, inst_lo = fields
        entries.append(
            ResourceEntry(
                key=ResourceKey(type_id, group_id, (inst_hi << 32) | inst_lo),
                offset=offset,
                size=raw_size & 0x7FFFFFFF,
                decompressed_size=decompressed,
                compression=compression,
            )
        )

    return entries


def _verify_entries(fh: BinaryIO, pkg: Package, limit: int | None = None) -> None:
    """Actually decompress records to prove the payload is intact."""
    checked = 0
    for entry in pkg.entries:
        if limit is not None and checked >= limit:
            break
        if entry.compression == COMP_DELETED:
            continue
        checked += 1

        fh.seek(entry.offset)
        blob = fh.read(entry.size)
        if len(blob) != entry.size:
            raise PackageError(f"resource {entry.key} is cut short inside the file")

        if entry.compression == COMP_ZLIB:
            try:
                data = zlib.decompress(blob)
            except zlib.error as exc:
                raise PackageError(
                    f"resource {entry.key} will not decompress ({exc}) -- "
                    f"the file is damaged"
                ) from exc
            if len(data) != entry.decompressed_size:
                pkg.anomalies.append(
                    f"resource {entry.key} decompressed to {len(data)} bytes, "
                    f"index says {entry.decompressed_size}"
                )
        elif entry.compression not in UNCOMPRESSED:
            pkg.anomalies.append(
                f"resource {entry.key} uses unknown compression "
                f"0x{entry.compression:04X}"
            )
