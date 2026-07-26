"""Walk a Mods folder and work out what is broken."""

from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .dbpf import Package, PackageError, read_package
from .resource_types import is_low_impact, type_name
from .scripts import GAME_PYTHON, ScriptError, ScriptMod, read_script_mod

# The game stops looking for .package files this many folders below Mods.
MAX_PACKAGE_DEPTH = 5
# Script mods are only picked up in Mods/ or one folder below it.
MAX_SCRIPT_DEPTH = 1

BROKEN = "broken"
WARNING = "warning"
INFO = "info"

_LEVEL_ORDER = {BROKEN: 0, WARNING: 1, INFO: 2}

ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".gz", ".tar", ".rar5"}
JUNK_EXTS = {
    ".txt", ".rtf", ".pdf", ".doc", ".docx", ".html", ".htm", ".url",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".mp4", ".webm",
}
DISABLED_MARKERS = (".bak", ".old", ".disabled", ".off", ".backup", ".orig")


@dataclass
class Finding:
    level: str
    code: str
    message: str
    path: str = ""
    fix: str = ""
    details: list[str] = field(default_factory=list)

    @property
    def sort_key(self) -> tuple[int, str, str]:
        return (_LEVEL_ORDER.get(self.level, 9), self.code, self.path)


@dataclass
class ScanResult:
    root: str
    started_at: float = 0.0
    duration: float = 0.0
    deep: bool = False
    packages_ok: int = 0
    packages_broken: int = 0
    scripts_ok: int = 0
    scripts_broken: int = 0
    other_files: int = 0
    total_bytes: int = 0
    total_resources: int = 0
    findings: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def by_level(self, level: str) -> list[Finding]:
        return [f for f in self.findings if f.level == level]

    @property
    def mod_count(self) -> int:
        return (
            self.packages_ok
            + self.packages_broken
            + self.scripts_ok
            + self.scripts_broken
        )

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: f.sort_key)


@dataclass
class _FileJob:
    path: str
    rel: str
    depth: int
    size: int


def scan(
    root: str,
    deep: bool = False,
    check_conflicts: bool = True,
    check_duplicates: bool = True,
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ScanResult:
    """Scan `root` (a Mods folder) and return everything worth reporting.

    deep -- also decompress every resource and CRC-check every archive.  Much
    slower, but it is the only way to catch a file that is structurally fine
    and internally rotten.
    """
    root = os.path.abspath(root)
    result = ScanResult(root=root, started_at=time.time(), deep=deep)

    packages, scripts, others, dirs = _collect(root, result)

    if not packages and not scripts:
        result.add(
            Finding(
                level=WARNING,
                code="no-mods",
                message=(
                    "No .package or .ts4script files found anywhere under this folder."
                ),
                path=root,
                fix=(
                    "Check you pointed at the Mods folder itself, usually "
                    "Documents/Electronic Arts/The Sims 4/Mods."
                ),
            )
        )

    _check_layout(root, dirs, result)

    total = len(packages) + len(scripts)
    done = 0
    workers = workers or min(8, (os.cpu_count() or 2) * 2)

    parsed_packages: list[tuple[_FileJob, Package | None, str]] = []
    parsed_scripts: list[tuple[_FileJob, ScriptMod | None, str]] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for job, pkg, err in pool.map(lambda j: _load_package(j, deep), packages):
            parsed_packages.append((job, pkg, err))
            done += 1
            if progress and done % 25 == 0:
                progress(done, total)
        for job, mod, err in pool.map(lambda j: _load_script(j, deep), scripts):
            parsed_scripts.append((job, mod, err))
            done += 1
            if progress and done % 25 == 0:
                progress(done, total)

    if progress:
        progress(total, total)

    for job, pkg, err in parsed_packages:
        _report_package(job, pkg, err, result)
    for job, mod, err in parsed_scripts:
        _report_script(job, mod, err, result)

    for job in others:
        result.other_files += 1
        _report_other(job, result)

    if check_duplicates:
        _check_duplicates(packages + scripts, result)

    if check_conflicts:
        _check_conflicts(parsed_packages, result)

    result.duration = time.time() - result.started_at
    return result


def _collect(
    root: str, result: ScanResult
) -> tuple[list[_FileJob], list[_FileJob], list[_FileJob], list[str]]:
    packages: list[_FileJob] = []
    scripts: list[_FileJob] = []
    others: list[_FileJob] = []
    dirs: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""
            depth = 0
        else:
            dirs.append(rel_dir)
            depth = len(rel_dir.split(os.sep))

        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            rel = os.path.join(rel_dir, name) if rel_dir else name
            try:
                size = os.path.getsize(path)
            except OSError as exc:
                result.add(
                    Finding(
                        level=WARNING,
                        code="unreadable",
                        message=f"Could not read this file: {exc.strerror or exc}",
                        path=rel,
                        fix="Check file permissions, or that the drive is still connected.",
                    )
                )
                continue

            result.total_bytes += size
            job = _FileJob(path=path, rel=rel, depth=depth, size=size)
            lower = name.lower()
            if lower.endswith(".package"):
                packages.append(job)
            elif lower.endswith(".ts4script"):
                scripts.append(job)
            else:
                others.append(job)

    return packages, scripts, others, dirs


def _load_package(job: _FileJob, deep: bool) -> tuple[_FileJob, Package | None, str]:
    try:
        return job, read_package(job.path, verify_data=deep), ""
    except PackageError as exc:
        return job, None, str(exc)
    except OSError as exc:
        return job, None, f"could not read the file ({exc.strerror or exc})"


def _load_script(job: _FileJob, deep: bool) -> tuple[_FileJob, ScriptMod | None, str]:
    try:
        return job, read_script_mod(job.path, verify_data=deep), ""
    except ScriptError as exc:
        return job, None, str(exc)
    except OSError as exc:
        return job, None, f"could not read the file ({exc.strerror or exc})"


def _report_package(
    job: _FileJob, pkg: Package | None, err: str, result: ScanResult
) -> None:
    if pkg is None:
        result.packages_broken += 1
        result.add(
            Finding(
                level=BROKEN,
                code="bad-package",
                message=err,
                path=job.rel,
                fix="Delete this file and re-download it from the creator.",
            )
        )
        return

    result.packages_ok += 1
    result.total_resources += len(pkg.entries)

    if job.depth > MAX_PACKAGE_DEPTH:
        result.add(
            Finding(
                level=BROKEN,
                code="too-deep",
                message=(
                    f"Buried {job.depth} folders deep. The game only reads packages "
                    f"up to {MAX_PACKAGE_DEPTH} folders below Mods, so this one is "
                    f"never loaded."
                ),
                path=job.rel,
                fix="Move it closer to the top of the Mods folder.",
            )
        )

    if not pkg.entries:
        result.add(
            Finding(
                level=WARNING,
                code="empty-package",
                message="Valid package, but it contains no resources -- it does nothing.",
                path=job.rel,
                fix="Safe to delete unless the creator says otherwise.",
            )
        )

    for note in pkg.anomalies:
        result.add(
            Finding(
                level=WARNING,
                code="package-anomaly",
                message=note,
                path=job.rel,
                fix="Usually still loads, but re-download if the mod misbehaves.",
            )
        )


def _report_script(
    job: _FileJob, mod: ScriptMod | None, err: str, result: ScanResult
) -> None:
    if mod is None:
        result.scripts_broken += 1
        result.add(
            Finding(
                level=BROKEN,
                code="bad-script",
                message=err,
                path=job.rel,
                fix="Delete this file and re-download it from the creator.",
            )
        )
        return

    result.scripts_ok += 1

    if job.depth > MAX_SCRIPT_DEPTH:
        result.add(
            Finding(
                level=BROKEN,
                code="script-too-deep",
                message=(
                    f"Buried {job.depth} folders deep. Script mods only load from "
                    f"Mods itself or one folder below it, so this one never runs."
                ),
                path=job.rel,
                fix="Move it into Mods, or into a single subfolder of Mods.",
            )
        )

    wrong = mod.wrong_version_pycs
    if wrong:
        listed = ", ".join(f"{n} file(s) for Python {v}" for v, n in sorted(wrong.items()))
        all_wrong = mod.pyc_files > 0 and sum(wrong.values()) == mod.pyc_files
        result.add(
            Finding(
                level=BROKEN if all_wrong else WARNING,
                code="wrong-python",
                message=(
                    f"Compiled for the wrong Python: {listed}. The game runs "
                    f"Python {GAME_PYTHON}."
                ),
                path=job.rel,
                fix=(
                    "This is an outdated script mod -- check the creator's page "
                    "for a version updated for the current patch."
                ),
            )
        )

    if mod.nested_archives:
        result.add(
            Finding(
                level=WARNING,
                code="nested-archive",
                message=(
                    f"Contains {len(mod.nested_archives)} archive(s) inside it "
                    f"(e.g. {mod.nested_archives[0]}), which the game will not open."
                ),
                path=job.rel,
                fix="Usually means the mod was zipped twice -- unpack and re-check.",
            )
        )

    if mod.pyc_files == 0 and mod.py_files > 0 and not mod.has_init:
        result.add(
            Finding(
                level=WARNING,
                code="no-package-init",
                message=(
                    "Only loose .py source files and no __init__.py -- this may not "
                    "import as a package."
                ),
                path=job.rel,
                fix="Check that you downloaded the release build, not the source.",
            )
        )


def _report_other(job: _FileJob, result: ScanResult) -> None:
    name = os.path.basename(job.rel)
    lower = name.lower()
    stem, ext = os.path.splitext(lower)

    if name == ".DS_Store" or name.startswith("._") or "__MACOSX" in job.rel:
        result.add(
            Finding(
                level=INFO,
                code="mac-junk",
                message="macOS metadata file. Harmless, but it is clutter.",
                path=job.rel,
                fix="Safe to delete.",
            )
        )
        return

    if ext in ARCHIVE_EXTS:
        result.add(
            Finding(
                level=BROKEN,
                code="not-extracted",
                message=(
                    "An archive sitting in Mods. The game cannot read inside "
                    "archives, so whatever is in here is not installed."
                ),
                path=job.rel,
                fix="Extract it, then delete the archive.",
            )
        )
        return

    if any(lower.endswith(m) for m in DISABLED_MARKERS) or ".package." in lower:
        result.add(
            Finding(
                level=INFO,
                code="disabled-file",
                message="Renamed/backup mod file. The game ignores it.",
                path=job.rel,
                fix="Delete it, or rename back to .package if you want it active.",
            )
        )
        return

    if lower in ("resource.cfg", "resource.cfg.bak"):
        return

    if ext in JUNK_EXTS:
        result.add(
            Finding(
                level=INFO,
                code="stray-file",
                message="Not a mod file -- readme, preview image or similar.",
                path=job.rel,
                fix="Harmless. Delete it if you want a tidy folder.",
            )
        )
        return

    result.add(
        Finding(
            level=INFO,
            code="unknown-file",
            message=f"Unrecognised file type '{ext or 'no extension'}' -- the game ignores it.",
            path=job.rel,
            fix="Check whether it was supposed to be a .package or .ts4script.",
        )
    )


def _check_layout(root: str, dirs: Iterable[str], result: ScanResult) -> None:
    for rel in dirs:
        parts = rel.split(os.sep)
        if parts[-1].lower() == "mods":
            result.add(
                Finding(
                    level=WARNING,
                    code="nested-mods-folder",
                    message="A folder named 'Mods' inside your Mods folder.",
                    path=rel,
                    fix=(
                        "Usually an unpacking mistake -- move its contents up one "
                        "level and delete the empty folder."
                    ),
                )
            )

    if not os.path.exists(os.path.join(root, "Resource.cfg")):
        result.add(
            Finding(
                level=INFO,
                code="no-resource-cfg",
                message=(
                    "No Resource.cfg in the Mods folder. Current game versions do "
                    "not need one, but it is missing if you expected it."
                ),
                path="Resource.cfg",
                fix="Ignore this unless mods are not loading at all.",
            )
        )


def _hash_file(path: str, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _check_duplicates(jobs: list[_FileJob], result: ScanResult) -> None:
    # Only hash files that share a size with another file -- everything else
    # cannot possibly be a byte-identical duplicate.
    by_size: dict[int, list[_FileJob]] = {}
    for job in jobs:
        by_size.setdefault(job.size, []).append(job)

    by_hash: dict[str, list[_FileJob]] = {}
    for size, group in by_size.items():
        if len(group) < 2 or size == 0:
            continue
        for job in group:
            try:
                by_hash.setdefault(_hash_file(job.path), []).append(job)
            except OSError:
                continue

    for digest, group in sorted(by_hash.items()):
        if len(group) < 2:
            continue
        paths = sorted(j.rel for j in group)
        wasted = group[0].size * (len(group) - 1)
        result.add(
            Finding(
                level=WARNING,
                code="duplicate",
                message=(
                    f"{len(group)} identical copies of the same mod "
                    f"({_human(wasted)} wasted, and duplicates fight each other)."
                ),
                path=paths[0],
                fix="Keep one copy and delete the rest.",
                details=paths,
            )
        )

    # Same filename in two places with different contents -- almost always an
    # old version left behind next to the update.
    by_name: dict[str, list[_FileJob]] = {}
    for job in jobs:
        by_name.setdefault(os.path.basename(job.rel).lower(), []).append(job)

    seen_as_dupe = {j.rel for group in by_hash.values() if len(group) > 1 for j in group}
    for name, group in sorted(by_name.items()):
        if len(group) < 2:
            continue
        if all(j.rel in seen_as_dupe for j in group):
            continue  # already reported as an exact duplicate
        paths = sorted(j.rel for j in group)
        result.add(
            Finding(
                level=WARNING,
                code="same-name",
                message=(
                    f"'{name}' exists in {len(group)} places with different contents "
                    f"-- probably an old version next to the new one."
                ),
                path=paths[0],
                fix="Keep the newest and delete the others.",
                details=paths,
            )
        )


@dataclass
class _Clash:
    """How badly one set of packages steps on itself."""

    high: int = 0
    low: int = 0
    types: set[int] = field(default_factory=set)

    @property
    def total(self) -> int:
        return self.high + self.low


def _check_conflicts(
    parsed: list[tuple[_FileJob, Package | None, str]], result: ScanResult
) -> None:
    # Pack each resource key into one int so the index stays cheap even for
    # folders with millions of resources.
    owners: dict[int, object] = {}
    files: list[str] = []

    for idx, (job, pkg, _err) in enumerate(parsed):
        if pkg is None:
            files.append(job.rel)
            continue
        files.append(job.rel)
        for entry in pkg.entries:
            packed = (
                (entry.key.type << 96) | (entry.key.group << 64) | entry.key.instance
            )
            existing = owners.get(packed)
            if existing is None:
                owners[packed] = idx
            elif isinstance(existing, int):
                if existing != idx:
                    owners[packed] = [existing, idx]
            elif idx not in existing:
                existing.append(idx)

    # Collapse per-resource clashes into per-file-group clashes; nobody wants a
    # list of 40,000 instance ids.
    groups: dict[tuple[int, ...], _Clash] = {}
    for packed, owner in owners.items():
        if isinstance(owner, int):
            continue
        type_id = packed >> 96
        clash = groups.setdefault(tuple(sorted(owner)), _Clash())
        if is_low_impact(type_id):
            clash.low += 1
        else:
            clash.high += 1
        clash.types.add(type_id)

    for group, clash in sorted(groups.items(), key=lambda kv: -kv[1].total):
        high = clash.high
        low = clash.low
        types = sorted(clash.types)
        paths = [files[i] for i in group]
        named = ", ".join(type_name(t) for t in types[:4])
        if len(types) > 4:
            named += f", +{len(types) - 4} more"

        if high == 0:
            result.add(
                Finding(
                    level=INFO,
                    code="soft-conflict",
                    message=(
                        f"{len(paths)} mods share {low} resource(s) ({named}). "
                        f"These types rarely cause real problems."
                    ),
                    path=paths[0],
                    fix="No action needed unless you see missing text or thumbnails.",
                    details=paths,
                )
            )
        else:
            result.add(
                Finding(
                    level=WARNING,
                    code="conflict",
                    message=(
                        f"{len(paths)} mods override the same {high} resource(s) "
                        f"({named}). Only the last one the game loads wins."
                    ),
                    path=paths[0],
                    fix=(
                        "If one of these mods is not working, this is why -- keep "
                        "one, or look for a compatibility patch."
                    ),
                    details=paths,
                )
            )


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
