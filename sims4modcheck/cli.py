"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import threading
import time

from . import report, scanner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sims4modcheck",
        description="Check a Sims 4 Mods folder for broken, misplaced or "
        "conflicting mods.",
    )
    parser.add_argument(
        "mods_folder",
        help="Path to your Mods folder "
        "(e.g. ~/Documents/Electronic Arts/The Sims 4/Mods)",
    )
    parser.add_argument(
        "--all", action="store_true", help="Also list informational notes."
    )
    parser.add_argument(
        "--json", metavar="FILE", help="Write the full results as JSON. Use - for stdout."
    )
    parser.add_argument(
        "--html", metavar="FILE", help="Write an HTML report you can open in a browser."
    )
    parser.add_argument(
        "--no-conflicts",
        action="store_true",
        help="Skip resource conflict detection (much faster on large folders).",
    )
    parser.add_argument(
        "--no-duplicates", action="store_true", help="Skip duplicate file detection."
    )
    parser.add_argument(
        "--max-conflicts",
        type=int,
        default=50,
        help="How many conflicting mod groups to report (default: 50).",
    )
    parser.add_argument(
        "--max-tracked-resources",
        type=int,
        default=scanner.DEFAULT_MAX_TRACKED_RESOURCES,
        metavar="N",
        help="Memory ceiling for conflict detection, in resources "
        f"(default: {scanner.DEFAULT_MAX_TRACKED_RESOURCES:,}, about 275 MB).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=scanner.DEFAULT_FILE_TIMEOUT,
        metavar="SECONDS",
        help="Give up on any single file after this long and carry on "
        f"(default: {scanner.DEFAULT_FILE_TIMEOUT:.0f}). 0 waits forever.",
    )
    parser.add_argument(
        "--quarantine",
        metavar="DIR",
        help="Move every file found BROKEN into DIR, preserving the folder "
        "layout. Nothing is deleted, and you are asked to confirm first.",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip the --quarantine confirmation prompt."
    )
    parser.add_argument("--quiet", action="store_true", help="Hide scan progress.")
    parser.add_argument(
        "--no-color", action="store_true", help="Disable coloured output."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = os.path.abspath(os.path.expanduser(args.mods_folder))

    if not os.path.isdir(root):
        print(f"Not a folder: {root}", file=sys.stderr)
        return 2

    watchdog = None if args.quiet else _Watchdog().start()
    progress = None if args.quiet else _make_progress(watchdog)
    try:
        result = scanner.scan(
            root,
            check_conflicts=not args.no_conflicts,
            check_duplicates=not args.no_duplicates,
            max_conflicts=args.max_conflicts,
            max_tracked_resources=args.max_tracked_resources,
            file_timeout=args.timeout,
            progress=progress,
        )
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    finally:
        if watchdog:
            watchdog.stop()
        if progress:
            print("\r\033[K", end="", file=sys.stderr)

    color = not args.no_color and sys.stdout.isatty()
    print(report.to_text(result, color=color, show_info=args.all))

    if args.json:
        _write(args.json, report.to_json(result))
    if args.html:
        _write(args.html, report.to_html(result))
        if args.html != "-":
            print(f"\nHTML report written to {args.html}")

    if args.quarantine:
        _quarantine(result, args.quarantine, assume_yes=args.yes)

    return 1 if result.errors else 0


# A file this size takes long enough to read that the counter would look stuck
# if we waited for the next batch to redraw.
_SLOW_FILE_BYTES = 20 * 1024 * 1024


# How long a single file may sit there before we say so out loud.
_NAG_AFTER_SECONDS = 5.0


class _Watchdog:
    """Reports when one file is taking a suspiciously long time.

    Without this a stalled read is indistinguishable from a crash: the counter
    stops and nothing explains why.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._path = None
        self._since = time.monotonic()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def note(self, path: str) -> None:
        with self._lock:
            self._path = path
            self._since = time.monotonic()

    def _watch(self) -> None:
        while not self._stop.wait(1.0):
            with self._lock:
                path, since = self._path, self._since
            waited = time.monotonic() - since
            if path and waited >= _NAG_AFTER_SECONDS:
                print(
                    f"\r\033[Kstill reading {os.path.basename(path)[:50]} "
                    f"({waited:.0f}s) -- waiting on the disk, not stuck",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )


def _make_progress(watchdog=None):
    state = {"scanning": 0, "hashing": 0}

    def progress(path: str, phase: str) -> None:
        state[phase] += 1
        n = state[phase]
        if watchdog:
            watchdog.note(path)
        # Mod files are where the real work happens, so always redraw before
        # one: if the scan stalls, the name on screen is the file responsible.
        # Everything else redraws in batches to keep the terminal quiet.
        interesting = os.path.splitext(path)[1].lower() in scanner.MOD_EXTS
        if not interesting and n % 25 and _size(path) < _SLOW_FILE_BYTES:
            return
        name = os.path.basename(path)[:60]
        label = (
            f"checked {n} files"
            if phase == scanner.SCANNING
            else f"comparing duplicates ({n})"
        )
        print(f"\r\033[K{label}... {name}", end="", file=sys.stderr, flush=True)

    return progress


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _write(target: str, text: str) -> None:
    if target == "-":
        print(text)
        return
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(text)


# A misplaced mod is a healthy file in the wrong folder. Pulling it out of Mods
# is not the fix, so quarantine leaves it alone.
_MISPLACED = {"too-deep", "script-too-deep"}


def _quarantine(result, dest: str, *, assume_yes: bool) -> None:
    broken = sorted(
        {
            issue.path
            for issue in result.errors
            if issue.code not in _MISPLACED and os.path.isfile(issue.path)
        }
    )
    if not broken:
        print("\nNothing to quarantine.")
        return

    dest = os.path.abspath(os.path.expanduser(dest))
    print(f"\nAbout to move {len(broken)} broken file(s) into {dest}")
    if not assume_yes:
        try:
            answer = input("Continue? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in {"y", "yes"}:
            print("Skipped.")
            return

    moved = 0
    for path in broken:
        target = os.path.join(dest, os.path.relpath(path, result.root))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        target = _unique(target)
        try:
            shutil.move(path, target)
            moved += 1
        except OSError as exc:
            print(f"  could not move {path}: {exc}", file=sys.stderr)
    print(f"Moved {moved} file(s).")


def _unique(path: str) -> str:
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


if __name__ == "__main__":
    raise SystemExit(main())
