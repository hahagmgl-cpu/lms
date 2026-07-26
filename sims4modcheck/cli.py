"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import shutil
import sys

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

    progress = None if args.quiet else _make_progress()
    try:
        result = scanner.scan(
            root,
            check_conflicts=not args.no_conflicts,
            check_duplicates=not args.no_duplicates,
            max_conflicts=args.max_conflicts,
            progress=progress,
        )
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    finally:
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


def _make_progress():
    state = {"n": 0}

    def progress(path: str) -> None:
        state["n"] += 1
        if state["n"] % 25 == 0:
            name = os.path.basename(path)[:60]
            print(f"\r\033[Kchecked {state['n']} files... {name}", end="", file=sys.stderr)

    return progress


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
