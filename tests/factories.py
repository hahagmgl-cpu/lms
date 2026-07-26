"""Builders for real package / script bytes, so tests exercise the parsers."""

from __future__ import annotations

import struct
import zipfile

from sims4modcheck import dbpf


def make_package(keys=(), *, major=2, minor=1, index_flags=0) -> bytes:
    """Build a minimal but structurally valid DBPF file containing `keys`."""
    keys = list(keys)
    index = bytearray(struct.pack("<I", index_flags))
    constants = {}
    for bit in range(4):
        if index_flags & (1 << bit):
            # Take the constant from the first key; tests only use constants
            # when all keys agree on that field.
            constants[bit] = _field(keys[0], bit)
            index += struct.pack("<I", constants[bit])

    for key in keys:
        for bit in range(4):
            if bit not in constants:
                index += struct.pack("<I", _field(key, bit))
        # position, filesize, memsize, compression, committed
        index += struct.pack("<IIIHH", 0, 0, 0, 0, 1)

    header = bytearray(b"\0" * dbpf.HEADER_SIZE)
    header[0:4] = b"DBPF"
    struct.pack_into("<I", header, 4, major)
    struct.pack_into("<I", header, 8, minor)
    struct.pack_into("<I", header, 36, len(keys))
    struct.pack_into("<I", header, 44, len(index))
    struct.pack_into("<I", header, 64, dbpf.HEADER_SIZE)
    return bytes(header) + bytes(index)


def _field(key: dbpf.ResourceKey, bit: int) -> int:
    return {
        0: key.type,
        1: key.group,
        2: (key.instance >> 32) & 0xFFFFFFFF,
        3: key.instance & 0xFFFFFFFF,
    }[bit]


def key(type_id=0x0333406C, group=0, instance=0x1122334455667788) -> dbpf.ResourceKey:
    return dbpf.ResourceKey(type=type_id, group=group, instance=instance)


def write_script(path, *, magic=3394, names=("mod/main.pyc",), source_names=()):
    """Write a .ts4script archive whose .pyc files carry `magic`."""
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            header = magic.to_bytes(2, "little") + b"\r\n" + b"\0" * 12
            zf.writestr(name, header + b"payload")
        for name in source_names:
            zf.writestr(name, "print('hi')\n")
    return path
