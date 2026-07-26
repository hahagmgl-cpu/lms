"""Command line entry point."""

from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
import threading
import time

from . import bisect as bisect_mod
from . import report, scanner

BISECT_DIRNAME = "Mods (set aside)"


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
        "--quick",
        action="store_true",
        help="Just check whether each mod is broken. Skips conflict and "
        "duplicate detection, which are the slow parts.",
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
        "--find-culprit",
        action="store_true",
        help="Track down the single mod causing a problem the file checks "
        "cannot see -- a black main menu, CAS not opening, saves failing. "
        "Moves half your mods aside, you launch the game and say whether the "
        "problem is still there, and it narrows down from there. Every mod is "
        "put back afterwards.",
    )
    parser.add_argument(
        "--fix-warnings",
        action="store_true",
        help="Also act on warnings, not just broken mods: delete extra copies "
        "of duplicated mods (keeping one), move mods that are buried too deep "
        "up to where the game can load them, and clear out unfinished "
        "downloads. Conflicts and unreadable files are left alone -- see the "
        "README for why.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Permanently delete instead of moving to a folder. There is no "
        "undo; without this, everything is recoverable.",
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help=f"Take the broken mods out of your Mods folder. They are moved "
        f"into a '{QUARANTINE_DIRNAME}' folder next to Mods, not deleted, so "
        "you can put any of them back. You are asked to confirm first.",
    )
    parser.add_argument(
        "--quarantine",
        metavar="DIR",
        help="Like --remove, but you choose where the broken mods go.",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip the confirmation prompt."
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

    if args.find_culprit:
        return _find_culprit(root)

    watchdog = None if args.quiet else _Watchdog().start()
    progress = None if args.quiet else _make_progress(watchdog)
    try:
        result = scanner.scan(
            root,
            check_conflicts=not (args.no_conflicts or args.quick),
            check_duplicates=not (args.no_duplicates or args.quick),
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

    dest = args.quarantine
    if (args.remove or args.fix_warnings or args.delete) and not dest:
        # A sibling of Mods: outside what the game loads, and on the same disk
        # so the move is instant rather than a copy.
        dest = os.path.join(os.path.dirname(root), QUARANTINE_DIRNAME)
    if dest:
        _apply(
            result,
            _plan(result, fix_warnings=args.fix_warnings),
            dest,
            assume_yes=args.yes,
            delete=args.delete,
        )

    return 1 if result.errors else 0


# A file this size takes long enough to read that the counter would look stuck
# if we waited for the next batch to redraw.
_SLOW_FILE_BYTES = 20 * 1024 * 1024


# Where --remove puts broken mods: a sibling of Mods, so the game stops loading
# them but the user can still get them back.
QUARANTINE_DIRNAME = "Broken Mods"

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


def _find_culprit(root: str) -> int:
    holding = os.path.join(os.path.dirname(root), BISECT_DIRNAME)
    total = len(bisect_mod.collect_mods(root))
    if total < 2:
        print("Need at least two mods installed to narrow anything down.")
        return 0

    rounds = max(1, math.ceil(math.log2(total)))
    print(
        f"{total} mods installed. This takes about {rounds} game launches.\n"
        f"Mods are moved to '{holding}' while testing and put back at the end -- "
        "including if you quit part way through.\n"
        "Quit the game fully between rounds, or it won't pick up the change."
    )

    def ask(kept: int, of: int) -> str:
        while True:
            print(
                f"\nLaunch the game now, with {kept} of these {of} mods active.",
            )
            try:
                answer = input("Is the problem still there? [y]es / [n]o / [q]uit: ")
            except EOFError:
                return bisect_mod.ABORT
            answer = answer.strip().lower()
            if answer in {"y", "yes"}:
                return bisect_mod.STILL_BROKEN
            if answer in {"n", "no"}:
                return bisect_mod.FIXED
            if answer in {"q", "quit"}:
                return bisect_mod.ABORT
            print("Please answer y, n or q.")

    try:
        outcome = bisect_mod.bisect(root, holding, ask)
    except KeyboardInterrupt:
        print("\nStopped. All mods have been put back.")
        return 130

    if outcome.aborted:
        print("\nStopped. All mods have been put back.")
        return 0
    if outcome.culprit:
        print(
            f"\nFound it: {os.path.relpath(outcome.culprit, root)}\n"
            f"That is the mod causing your problem, narrowed down in "
            f"{outcome.rounds} rounds. Every mod is back in place, so move that "
            "one out and check for an updated version from its creator."
        )
        return 1
    return 0


def _write(target: str, text: str) -> None:
    if target == "-":
        print(text)
        return
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(text)


# A mod buried too deep is a healthy file in the wrong folder. Taking it out of
# Mods is not the fix -- moving it up is -- so plain removal skips these.
_MISPLACED = {"too-deep", "script-too-deep"}

# Warnings where the file itself is genuinely unwanted.
_JUNK_WARNINGS = {"inert-file", "script-mixed-python"}

# Warnings we deliberately never act on:
#   conflict      -- overriding the same resource is usually intentional, and
#                    picking a loser automatically would delete working mods.
#   read-timeout  -- the file was never successfully read, so we know nothing
#                    about it. Acting on ignorance is not a fix.
_NEVER_ACT = {"conflict", "read-timeout", "conflicts-truncated", "conflicts-incomplete"}


def _plan(result, *, fix_warnings: bool):
    """Work out what to do with each file, as (action, path, reason) rows.

    Action is "remove" (out of Mods) or "relocate" (up to where the game
    actually loads it).
    """
    planned: dict[str, tuple[str, str]] = {}

    def add(action: str, path: str, reason: str) -> None:
        if os.path.isfile(path) and path not in planned:
            planned[path] = (action, reason)

    for issue in result.issues:
        if issue.code in _NEVER_ACT:
            continue
        if issue.code in _MISPLACED:
            if fix_warnings:
                add("relocate", issue.path, "buried too deep for the game to load")
            continue
        if issue.severity == scanner.ERROR:
            add("remove", issue.path, issue.message.split(".")[0].split(" -- ")[0])
        elif fix_warnings and issue.code == "duplicate":
            # issue.path is the copy we keep; the extras go.
            for extra in issue.related:
                add("remove", extra, "duplicate copy of a mod you already have")
        elif fix_warnings and issue.code in _JUNK_WARNINGS:
            add("remove", issue.path, issue.message.split(".")[0])

    return sorted((action, path, reason) for path, (action, reason) in planned.items())


def _apply(result, plan, dest: str, *, assume_yes: bool, delete: bool) -> None:
    if not plan:
        print("\nNothing to clean up.")
        return

    removals = [row for row in plan if row[0] == "remove"]
    moves = [row for row in plan if row[0] == "relocate"]
    dest = os.path.abspath(os.path.expanduser(dest))

    print()
    if removals:
        verb = "delete" if delete else "take"
        print(f"About to {verb} {len(removals)} mod(s) out of your Mods folder:")
        for _, path, reason in removals[:10]:
            print(f"  {os.path.relpath(path, result.root)} -- {reason}")
        if len(removals) > 10:
            print(f"  ...and {len(removals) - 10} more")
        print(
            "They will be permanently deleted. This cannot be undone."
            if delete
            else f"They will be moved to {dest} -- nothing is deleted."
        )
    if moves:
        print(f"About to move {len(moves)} mod(s) up into {result.root}:")
        for _, path, reason in moves[:10]:
            print(f"  {os.path.relpath(path, result.root)} -- {reason}")
        if len(moves) > 10:
            print(f"  ...and {len(moves) - 10} more")

    if not assume_yes:
        try:
            answer = input("Continue? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in {"y", "yes"}:
            print("Skipped.")
            return

    removed = relocated = 0
    for action, path, _ in plan:
        try:
            if action == "relocate":
                target = _unique(os.path.join(result.root, os.path.basename(path)))
                shutil.move(path, target)
                relocated += 1
            elif delete:
                os.remove(path)
                removed += 1
            else:
                target = _unique(os.path.join(dest, os.path.relpath(path, result.root)))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(path, target)
                removed += 1
        except OSError as exc:
            print(f"  could not handle {path}: {exc}", file=sys.stderr)

    if removed:
        print(
            f"Deleted {removed} mod(s)."
            if delete
            else f"Removed {removed} mod(s). They are in {dest} if you want them back."
        )
    if relocated:
        print(f"Moved {relocated} mod(s) up to the top of your Mods folder.")


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
