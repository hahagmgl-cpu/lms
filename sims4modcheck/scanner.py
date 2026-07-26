"""Walks a Mods folder and reports everything that looks broken."""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass, field

from . import dbpf, scripts

ERROR = "error"
WARNING = "warning"
INFO = "info"

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}

# Phases reported to a progress callback.
SCANNING = "scanning"
HASHING = "hashing"

# Conflict detection has to remember every resource key it has seen. Measured
# at ~92 bytes per tracked key (packed int plus its dict slot), so this ceiling
# caps the map at roughly 275 MB. Past that we stop tracking and say so, rather
# than swapping the user's machine to a standstill and looking like a hang.
DEFAULT_MAX_TRACKED_RESOURCES = 3_000_000

# The game only walks so far down into Mods. Anything deeper is never loaded,
# no matter how healthy the file itself is.
MAX_PACKAGE_DEPTH = 5
MAX_SCRIPT_DEPTH = 1

# Archives people forget to extract. The game cannot read these.
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".gz", ".tar", ".rar5"}

# Half-finished downloads and manually disabled mods.
INERT_EXTS = {
    ".part": "an unfinished download",
    ".crdownload": "an unfinished Chrome download",
    ".download": "an unfinished download",
    ".tmp": "a temporary file",
    ".bak": "a backup copy",
    ".disabled": "manually disabled",
    ".off": "manually disabled",
}

# Harmless clutter -- readmes, previews, licence files.
CLUTTER_EXTS = {
    ".txt", ".md", ".html", ".htm", ".url", ".pdf", ".doc", ".docx",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
}

MOD_EXTS = {".package", ".ts4script"}


@dataclass
class Issue:
    severity: str
    code: str
    path: str
    message: str
    fix: str = ""
    # Extra paths involved (the other side of a duplicate or conflict).
    related: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    root: str
    issues: list[Issue] = field(default_factory=list)
    package_count: int = 0
    script_count: int = 0
    other_count: int = 0
    total_bytes: int = 0

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == WARNING]

    @property
    def infos(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == INFO]

    def sorted_issues(self) -> list[Issue]:
        return sorted(
            self.issues, key=lambda i: (_SEVERITY_ORDER[i.severity], i.path, i.code)
        )


def scan(
    root: str,
    *,
    check_conflicts: bool = True,
    check_duplicates: bool = True,
    max_conflicts: int = 50,
    max_tracked_resources: int = DEFAULT_MAX_TRACKED_RESOURCES,
    progress=None,
) -> ScanResult:
    """Scan a Mods folder.

    progress, if given, is called as progress(path, phase) for each file as it
    is examined. Phase is one of "scanning" or "hashing" -- hashing runs after
    the walk and can take a while on its own, so it reports separately rather
    than leaving the caller looking at a frozen counter.
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise NotADirectoryError(root)

    result = ScanResult(root=root)
    # Packed resource key -> package that first provided it. Only actual
    # collisions get promoted to a full list, so memory stays at one entry per
    # resource rather than one per (resource, package) pair.
    first_owner: dict[int, str] = {}
    collisions: dict[int, list[str]] = defaultdict(list)
    by_size: dict[int, list[str]] = defaultdict(list)
    budget = {"remaining": max_tracked_resources, "dropped": 0}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if progress:
                progress(path, SCANNING)
            _check_file(
                path,
                root,
                result,
                first_owner,
                collisions,
                by_size,
                budget,
                check_conflicts=check_conflicts,
                check_duplicates=check_duplicates,
            )

    duplicate_groups: list[frozenset[str]] = []
    if check_duplicates:
        duplicate_groups = _report_duplicates(by_size, result, progress)
    if check_conflicts:
        _report_conflicts(collisions, result, max_conflicts, duplicate_groups)
        if budget["dropped"]:
            result.issues.append(
                Issue(
                    INFO,
                    "conflicts-incomplete",
                    root,
                    f"Stopped tracking conflicts after {max_tracked_resources:,} "
                    f"resources to stay within memory, so {budget['dropped']:,} "
                    "later resources were not compared. Everything else in this "
                    "report is unaffected.",
                    fix="Run with --no-conflicts for a quick check, or raise "
                    "--max-tracked-resources if you have RAM to spare.",
                )
            )
    return result


def _check_file(
    path,
    root,
    result,
    first_owner,
    collisions,
    by_size,
    budget,
    *,
    check_conflicts,
    check_duplicates,
):
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    rel = os.path.relpath(path, root)
    depth = rel.count(os.sep)

    try:
        size = os.path.getsize(path)
    except OSError as exc:
        result.issues.append(
            Issue(ERROR, "unreadable", path, f"Could not read the file: {exc}")
        )
        return
    result.total_bytes += size

    if ext in MOD_EXTS and size == 0:
        result.package_count += 1 if ext == ".package" else 0
        result.script_count += 1 if ext == ".ts4script" else 0
        result.issues.append(
            Issue(
                ERROR,
                "empty-file",
                path,
                "The file is 0 bytes -- the download failed or the file was truncated.",
                fix="Delete it and download the mod again.",
            )
        )
        return

    if ext == ".package":
        result.package_count += 1
        if check_duplicates:
            by_size[size].append(path)
        _check_package(
            path, depth, result, first_owner, collisions, budget, check_conflicts
        )
    elif ext == ".ts4script":
        result.script_count += 1
        if check_duplicates:
            by_size[size].append(path)
        _check_script(path, depth, result)
    else:
        result.other_count += 1
        _check_other(path, name, ext, result)


def _check_package(path, depth, result, first_owner, collisions, budget, check_conflicts):
    try:
        package = dbpf.read_package(path, read_index=check_conflicts, packed=True)
    except dbpf.DBPFError as exc:
        result.issues.append(
            Issue(
                ERROR,
                "bad-package",
                path,
                f"Not a working package: {exc}",
                fix="Re-download the mod. If the download keeps failing, the "
                "creator's file itself may be broken.",
            )
        )
        return
    except OSError as exc:
        result.issues.append(
            Issue(ERROR, "unreadable", path, f"Could not read the file: {exc}")
        )
        return

    if not package.is_ts4:
        result.issues.append(
            Issue(
                ERROR,
                "wrong-game",
                path,
                f"This is a DBPF {package.major}.{package.minor} package. The Sims 4 "
                f"only loads {dbpf.TS4_VERSION[0]}.{dbpf.TS4_VERSION[1]} packages, so "
                "the game ignores this file.",
                fix="This is almost certainly a Sims 2 or Sims 3 mod. Remove it.",
            )
        )
        return

    if depth > MAX_PACKAGE_DEPTH:
        result.issues.append(
            Issue(
                WARNING,
                "too-deep",
                path,
                f"Buried {depth} folders deep. The game only reads {MAX_PACKAGE_DEPTH} "
                "levels below Mods, so this file is never loaded.",
                fix="Move it closer to the top of your Mods folder.",
            )
        )

    if check_conflicts:
        for key in package.keys:
            owner = first_owner.get(key)
            if owner is None:
                # Known keys still register collisions once the budget is
                # spent; only brand new ones are dropped.
                if budget["remaining"] <= 0:
                    budget["dropped"] += 1
                    continue
                budget["remaining"] -= 1
                first_owner[key] = path
            elif owner != path:
                bucket = collisions[key]
                if not bucket:
                    bucket.append(owner)
                if path not in bucket:
                    bucket.append(path)


def _check_script(path, depth, result):
    try:
        mod = scripts.read_script_mod(path)
    except scripts.ScriptError as exc:
        result.issues.append(
            Issue(
                ERROR,
                "bad-script",
                path,
                f"Not a working script mod: {exc}",
                fix="Re-download the mod.",
            )
        )
        return

    if depth > MAX_SCRIPT_DEPTH:
        result.issues.append(
            Issue(
                ERROR,
                "script-too-deep",
                path,
                f"Buried {depth} folders deep. Script mods only load at the top of "
                f"Mods or {MAX_SCRIPT_DEPTH} folder below it, so this one never runs.",
                fix="Move it into Mods, or one folder inside Mods.",
            )
        )

    if mod.pyc_count == 0:
        if mod.py_source_count:
            result.issues.append(
                Issue(
                    ERROR,
                    "script-not-compiled",
                    path,
                    "Contains only .py source and no compiled .pyc files. The game "
                    "cannot run uncompiled scripts.",
                    fix="Download the release build rather than the source archive.",
                )
            )
        else:
            result.issues.append(
                Issue(
                    WARNING,
                    "script-empty",
                    path,
                    "Contains no Python at all, so it does nothing.",
                )
            )
        return

    bad = mod.bad_magics
    if bad and len(bad) == len(mod.magics):
        versions = ", ".join(
            f"{scripts.version_for_magic(m)} ({n} file{'s' if n != 1 else ''})"
            for m, n in sorted(bad.items())
        )
        result.issues.append(
            Issue(
                ERROR,
                "script-wrong-python",
                path,
                f"Built for Python {versions}, but the game runs Python "
                f"{scripts.GAME_PYTHON_VERSION}. It will not load.",
                fix="Look for an updated version of this mod.",
            )
        )
    elif bad:
        versions = ", ".join(scripts.version_for_magic(m) for m in sorted(bad))
        result.issues.append(
            Issue(
                WARNING,
                "script-mixed-python",
                path,
                f"Mostly Python {scripts.GAME_PYTHON_VERSION}, but some files are "
                f"built for {versions}. Parts of the mod may fail at runtime.",
                fix="Check for an updated version of this mod.",
            )
        )


def _check_other(path, name, ext, result):
    if ext in ARCHIVE_EXTS:
        result.issues.append(
            Issue(
                ERROR,
                "unextracted-archive",
                path,
                "An archive sitting in Mods. The game cannot read inside archives, "
                "so nothing in it is loaded.",
                fix="Extract it and put the .package / .ts4script files in Mods, "
                "then delete the archive.",
            )
        )
    elif ext in INERT_EXTS:
        stem_ext = os.path.splitext(os.path.splitext(name)[0])[1].lower()
        looks_like_mod = stem_ext in MOD_EXTS
        result.issues.append(
            Issue(
                WARNING if looks_like_mod else INFO,
                "inert-file",
                path,
                f"Ignored by the game -- it is {INERT_EXTS[ext]}.",
                fix="Rename it back to its real extension if you want it, "
                "otherwise delete it.",
            )
        )
    elif ext in CLUTTER_EXTS:
        result.issues.append(
            Issue(
                INFO,
                "clutter",
                path,
                "Not a mod file; the game ignores it.",
                fix="Safe to leave, safe to delete.",
            )
        )
    else:
        result.issues.append(
            Issue(
                INFO,
                "unknown-file",
                path,
                f"Unrecognised file type '{ext or 'no extension'}'; the game ignores it.",
            )
        )


def _report_duplicates(by_size, result, progress=None) -> list[frozenset[str]]:
    groups: list[frozenset[str]] = []
    for size, paths in by_size.items():
        if len(paths) < 2 or size == 0:
            continue
        by_hash: dict[str, list[str]] = defaultdict(list)
        for path in paths:
            if progress:
                progress(path, HASHING)
            digest = _hash(path)
            if digest:
                by_hash[digest].append(path)
        for group in by_hash.values():
            if len(group) < 2:
                continue
            groups.append(frozenset(group))
            keep, *rest = sorted(group)
            result.issues.append(
                Issue(
                    WARNING,
                    "duplicate",
                    keep,
                    f"Installed {len(group)} times. Duplicate copies of the same mod "
                    "waste load time and can conflict with each other.",
                    fix="Keep one copy and delete the others.",
                    related=rest,
                )
            )
    return groups


def _report_conflicts(collisions, result, max_conflicts, duplicate_groups=()):
    # Group by the set of packages involved: one report per conflicting pair
    # reads far better than one per resource.
    by_group: dict[tuple[str, ...], int] = defaultdict(int)
    for paths in collisions.values():
        group = frozenset(paths)
        # Two byte-identical copies of one mod always "conflict" with
        # themselves. That is already reported as a duplicate; saying it twice
        # only makes the report harder to read.
        if any(group <= dup for dup in duplicate_groups):
            continue
        by_group[tuple(sorted(paths))] += 1

    ranked = sorted(by_group.items(), key=lambda kv: (-kv[1], kv[0]))
    for group, count in ranked[:max_conflicts]:
        keep, *rest = group
        result.issues.append(
            Issue(
                WARNING,
                "conflict",
                keep,
                f"Overrides the same {count} resource{'s' if count != 1 else ''} as "
                f"{len(rest)} other mod{'s' if len(rest) != 1 else ''}. Only one of "
                "them wins in game, and which one is not predictable.",
                fix="If either mod misbehaves, remove one of them.",
                related=list(rest),
            )
        )
    hidden = len(ranked) - max_conflicts
    if hidden > 0:
        result.issues.append(
            Issue(
                INFO,
                "conflicts-truncated",
                result.root,
                f"{hidden} more conflicting mod group{'s' if hidden != 1 else ''} not "
                "shown. Raise --max-conflicts to see them all.",
            )
        )


def _hash(path: str) -> str | None:
    digest = hashlib.sha1()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()
