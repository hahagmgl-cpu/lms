"""Find the one mod causing a problem, by halving the folder.

Some breakage cannot be seen in the files at all. A black main menu, a mod that
stops the game saving, CAS refusing to open -- the package is structurally
perfect, it just does something the current patch no longer supports. The only
way to find it is to remove half your mods, launch the game, and see which half
the problem follows. That is a dozen rounds of tedious dragging by hand; the
computer can do the dragging.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

MOD_EXTS = {".package", ".ts4script"}

STILL_BROKEN = "broken"
FIXED = "fixed"
ABORT = "abort"


@dataclass
class BisectResult:
    culprit: str | None = None
    rounds: int = 0
    aborted: bool = False
    tested: int = 0


def collect_mods(root: str) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() in MOD_EXTS:
                found.append(os.path.join(dirpath, name))
    return found


def bisect(root: str, holding: str, ask, say=print) -> BisectResult:
    """Narrow `root` down to the single mod that reproduces a problem.

    `ask` is called each round with (kept, total) and must return STILL_BROKEN,
    FIXED or ABORT. Every mod is put back where it came from before returning,
    whatever the outcome.
    """
    root = os.path.abspath(root)
    holding = os.path.abspath(holding)
    suspects = collect_mods(root)
    result = BisectResult(tested=len(suspects))

    if len(suspects) < 2:
        say("Need at least two mods to narrow down. Nothing to do.")
        return result

    moved: dict[str, str] = {}
    try:
        while len(suspects) > 1:
            result.rounds += 1
            keep = suspects[: len(suspects) // 2]
            park = suspects[len(suspects) // 2 :]

            for path in park:
                moved[path] = _park(path, root, holding)
            say(
                f"\nRound {result.rounds}: {len(keep)} of {len(suspects)} mods left "
                f"in your Mods folder, {len(park)} moved aside."
            )

            answer = ask(len(keep), len(suspects))
            if answer == ABORT:
                result.aborted = True
                return result
            # If the problem survived, it came from what stayed behind.
            suspects = keep if answer == STILL_BROKEN else park
            _restore(moved)

        result.culprit = suspects[0]
        return result
    finally:
        _restore(moved)
        _prune(holding)


def _park(path: str, root: str, holding: str) -> str:
    target = os.path.join(holding, os.path.relpath(path, root))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.move(path, target)
    return target


def _restore(moved: dict[str, str]) -> None:
    for original, parked in list(moved.items()):
        if os.path.exists(parked):
            os.makedirs(os.path.dirname(original), exist_ok=True)
            shutil.move(parked, original)
        moved.pop(original, None)


def _prune(holding: str) -> None:
    """Remove the holding folder if the restore emptied it.

    Emptiness is checked with a fresh listdir rather than os.walk's dirnames,
    which is captured before the walk descends and so still lists children we
    have just removed.
    """
    for dirpath, _, _ in os.walk(holding, topdown=False):
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass
