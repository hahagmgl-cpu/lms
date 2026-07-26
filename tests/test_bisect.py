import os

import pytest

from sims4modcheck import bisect as bisect_mod
from tests import factories


@pytest.fixture
def mods(tmp_path):
    root = tmp_path / "Mods"
    root.mkdir()
    return root


def populate(root, count, subfolder=None):
    """Install `count` mods, returning their paths in walk order."""
    target = root / subfolder if subfolder else root
    target.mkdir(parents=True, exist_ok=True)
    for n in range(count):
        (target / f"mod{n:02d}.package").write_bytes(
            factories.make_package([factories.key(instance=n)])
        )
    return bisect_mod.collect_mods(str(root))


def player(culprit, log=None):
    """Answer each round as a player would: is the culprit still installed?"""

    def ask(kept, of):
        if log is not None:
            log.append((kept, of))
        return (
            bisect_mod.STILL_BROKEN
            if os.path.exists(culprit)
            else bisect_mod.FIXED
        )

    return ask


def test_finds_the_culprit(mods, tmp_path):
    paths = populate(mods, 16)
    culprit = paths[11]
    outcome = bisect_mod.bisect(
        str(mods), str(tmp_path / "held"), player(culprit), say=lambda *a: None
    )
    assert outcome.culprit == culprit


@pytest.mark.parametrize("index", [0, 1, 6, 9, 12])
def test_finds_the_culprit_wherever_it_sits(mods, tmp_path, index):
    paths = populate(mods, 13)
    culprit = paths[index]
    outcome = bisect_mod.bisect(
        str(mods), str(tmp_path / "held"), player(culprit), say=lambda *a: None
    )
    assert outcome.culprit == culprit


def test_every_mod_is_put_back_afterwards(mods, tmp_path):
    paths = populate(mods, 12)
    before = sorted(paths)
    bisect_mod.bisect(
        str(mods), str(tmp_path / "held"), player(paths[3]), say=lambda *a: None
    )
    assert sorted(bisect_mod.collect_mods(str(mods))) == before


def test_mods_are_put_back_even_if_the_user_quits(mods, tmp_path):
    paths = populate(mods, 12)
    before = sorted(paths)
    outcome = bisect_mod.bisect(
        str(mods), str(tmp_path / "held"), lambda *a: bisect_mod.ABORT,
        say=lambda *a: None,
    )
    assert outcome.aborted
    assert sorted(bisect_mod.collect_mods(str(mods))) == before


def test_mods_are_put_back_if_something_blows_up(mods, tmp_path):
    paths = populate(mods, 8)
    before = sorted(paths)

    def explode(kept, of):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        bisect_mod.bisect(
            str(mods), str(tmp_path / "held"), explode, say=lambda *a: None
        )
    assert sorted(bisect_mod.collect_mods(str(mods))) == before


def test_subfolder_layout_is_preserved(mods, tmp_path):
    paths = populate(mods, 8, subfolder="CC/Hair")
    outcome = bisect_mod.bisect(
        str(mods), str(tmp_path / "held"), player(paths[5]), say=lambda *a: None
    )
    assert outcome.culprit == paths[5]
    assert all(os.path.exists(p) for p in paths)
    assert "CC/Hair" in outcome.culprit.replace(os.sep, "/")


def test_round_count_is_logarithmic(mods, tmp_path):
    paths = populate(mods, 64)
    log = []
    bisect_mod.bisect(
        str(mods), str(tmp_path / "held"), player(paths[40], log), say=lambda *a: None
    )
    # 64 mods must not mean 64 game launches.
    assert len(log) <= 7


@pytest.mark.parametrize("subfolder", [None, "CC/Hair"])
def test_holding_folder_is_cleaned_up(mods, tmp_path, subfolder):
    # With mods in subfolders the holding folder gains nested directories, and
    # those have to go too or the user is left with clutter beside Mods.
    paths = populate(mods, 8, subfolder=subfolder)
    held = tmp_path / "held"
    bisect_mod.bisect(str(mods), str(held), player(paths[2]), say=lambda *a: None)
    assert not held.exists()


def test_nothing_to_do_with_a_single_mod(mods, tmp_path):
    populate(mods, 1)
    said = []
    outcome = bisect_mod.bisect(
        str(mods), str(tmp_path / "held"), player("nope"), say=said.append
    )
    assert outcome.culprit is None
    assert "at least two" in " ".join(said)
