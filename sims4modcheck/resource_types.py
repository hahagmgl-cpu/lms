"""Names for the resource types that show up in conflict reports.

Deliberately short: only types that are unambiguous and that a player would
recognise.  Anything else is reported as a raw hex id rather than guessed at.
"""

from __future__ import annotations

TYPE_NAMES: dict[int, str] = {
    0x034AEECB: "CAS Part",
    0x00B2D882: "Texture",
    0x220557DA: "String Table",
    0x545AC67A: "SimData",
    0x319E4F1D: "Object Definition",
    0x0166038C: "Name Map",
    0x01661233: "Model",
    0x01D0E75D: "Model LOD",
    0x01D10F34: "Material Definition",
    0x0333406C: "Tuning (XML)",
    0x3C1AF1F2: "Object Catalog",
    0x02019972: "Region Map",
    0x2F7D0004: "Animation Clip",
}

# Overriding these rarely breaks anything -- two mods can each add strings or
# thumbnails for the same id and the worst case is cosmetic.
LOW_IMPACT_TYPES = frozenset({0x220557DA, 0x00B2D882, 0x0166038C})


def type_name(type_id: int) -> str:
    known = TYPE_NAMES.get(type_id)
    return f"{known} (0x{type_id:08X})" if known else f"Type 0x{type_id:08X}"


def is_low_impact(type_id: int) -> bool:
    return type_id in LOW_IMPACT_TYPES
