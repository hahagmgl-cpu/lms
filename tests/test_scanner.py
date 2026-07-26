import os

import pytest

from sims4modcheck import scanner
from tests import factories


@pytest.fixture
def mods(tmp_path):
    root = tmp_path / "Mods"
    root.mkdir()
    return root


def codes(result, path_ends=None):
    return {
        i.code
        for i in result.issues
        if path_ends is None or i.path.endswith(path_ends)
    }


def test_healthy_folder_has_no_problems(mods):
    (mods / "good.package").write_bytes(factories.make_package([factories.key()]))
    factories.write_script(mods / "good.ts4script")
    result = scanner.scan(str(mods))
    assert result.errors == []
    assert result.warnings == []
    assert (result.package_count, result.script_count) == (1, 1)


def test_flags_empty_package(mods):
    (mods / "dead.package").write_bytes(b"")
    assert codes(scanner.scan(str(mods))) == {"empty-file"}


def test_flags_html_error_page_saved_as_package(mods):
    (mods / "oops.package").write_bytes(b"<html>404 not found</html>" + b"\0" * 200)
    result = scanner.scan(str(mods))
    assert codes(result) == {"bad-package"}
    assert result.errors[0].severity == scanner.ERROR


def test_flags_sims3_package(mods):
    (mods / "s3.package").write_bytes(factories.make_package(major=2, minor=0))
    assert codes(scanner.scan(str(mods))) == {"wrong-game"}


def test_flags_package_buried_too_deep(mods):
    deep = mods / "a" / "b" / "c" / "d" / "e" / "f"
    deep.mkdir(parents=True)
    (deep / "buried.package").write_bytes(factories.make_package())
    assert "too-deep" in codes(scanner.scan(str(mods)))


def test_package_within_depth_limit_is_fine(mods):
    ok = mods / "a" / "b" / "c" / "d" / "e"
    ok.mkdir(parents=True)
    (ok / "fine.package").write_bytes(factories.make_package())
    assert scanner.scan(str(mods)).issues == []


def test_flags_script_more_than_one_folder_deep(mods):
    deep = mods / "a" / "b"
    deep.mkdir(parents=True)
    factories.write_script(deep / "s.ts4script")
    assert "script-too-deep" in codes(scanner.scan(str(mods)))


def test_script_one_folder_deep_is_fine(mods):
    sub = mods / "a"
    sub.mkdir()
    factories.write_script(sub / "s.ts4script")
    assert scanner.scan(str(mods)).issues == []


def test_flags_script_built_for_old_python(mods):
    factories.write_script(mods / "old.ts4script", magic=3230)
    result = scanner.scan(str(mods))
    assert codes(result) == {"script-wrong-python"}
    assert "3.3" in result.errors[0].message


def test_flags_mixed_python_versions_as_warning(mods):
    path = mods / "mixed.ts4script"
    import zipfile

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("a.pyc", (3394).to_bytes(2, "little") + b"\r\n" + b"\0" * 12)
        zf.writestr("b.pyc", (3230).to_bytes(2, "little") + b"\r\n" + b"\0" * 12)
    result = scanner.scan(str(mods))
    assert codes(result) == {"script-mixed-python"}
    assert result.errors == []


def test_flags_source_only_script(mods):
    factories.write_script(mods / "src.ts4script", names=(), source_names=("a.py",))
    assert codes(scanner.scan(str(mods))) == {"script-not-compiled"}


def test_flags_corrupt_script(mods):
    (mods / "bad.ts4script").write_bytes(b"not a zip file at all")
    assert codes(scanner.scan(str(mods))) == {"bad-script"}


def test_flags_unextracted_archive(mods):
    (mods / "mod.zip").write_bytes(b"PK\x03\x04junk")
    result = scanner.scan(str(mods))
    assert codes(result) == {"unextracted-archive"}
    assert result.errors


def test_flags_unfinished_download_of_a_mod_as_warning(mods):
    (mods / "cc.package.crdownload").write_bytes(b"partial")
    result = scanner.scan(str(mods))
    assert [i.severity for i in result.issues] == [scanner.WARNING]


def test_readme_is_only_a_note(mods):
    (mods / "readme.txt").write_text("hi")
    result = scanner.scan(str(mods))
    assert codes(result) == {"clutter"}
    assert result.errors == [] and result.warnings == []


def test_finds_duplicate_mods(mods):
    data = factories.make_package([factories.key()])
    (mods / "cc.package").write_bytes(data)
    sub = mods / "backup"
    sub.mkdir()
    (sub / "cc.package").write_bytes(data)
    result = scanner.scan(str(mods))
    dupes = [i for i in result.issues if i.code == "duplicate"]
    assert len(dupes) == 1
    assert len(dupes[0].related) == 1


def test_same_size_different_content_is_not_a_duplicate(mods):
    (mods / "a.package").write_bytes(factories.make_package([factories.key(instance=1)]))
    (mods / "b.package").write_bytes(factories.make_package([factories.key(instance=2)]))
    assert [i for i in scanner.scan(str(mods)).issues if i.code == "duplicate"] == []


def test_duplicate_detection_can_be_disabled(mods):
    data = factories.make_package([factories.key()])
    (mods / "a.package").write_bytes(data)
    (mods / "b.package").write_bytes(data)
    result = scanner.scan(str(mods), check_duplicates=False)
    assert [i for i in result.issues if i.code == "duplicate"] == []


def test_finds_conflicting_overrides(mods):
    shared = [factories.key(instance=7), factories.key(instance=8)]
    (mods / "modA.package").write_bytes(factories.make_package(shared))
    (mods / "modB.package").write_bytes(
        factories.make_package(shared + [factories.key(instance=9)])
    )
    result = scanner.scan(str(mods))
    conflicts = [i for i in result.issues if i.code == "conflict"]
    assert len(conflicts) == 1
    assert "2 resources" in conflicts[0].message
    assert len(conflicts[0].related) == 1


def test_conflict_detection_can_be_disabled(mods):
    shared = [factories.key(instance=7)]
    (mods / "a.package").write_bytes(factories.make_package(shared))
    (mods / "b.package").write_bytes(factories.make_package(shared + [factories.key()]))
    result = scanner.scan(str(mods), check_conflicts=False)
    assert [i for i in result.issues if i.code == "conflict"] == []


def test_conflict_report_is_capped(mods):
    # Each pair shares one key but is not byte-identical, giving three
    # distinct conflicting groups.
    for n in range(3):
        shared = factories.key(instance=n)
        (mods / f"{n}a.package").write_bytes(factories.make_package([shared]))
        (mods / f"{n}b.package").write_bytes(
            factories.make_package([shared, factories.key(group=100 + n)])
        )
    result = scanner.scan(str(mods), max_conflicts=1)
    assert len([i for i in result.issues if i.code == "conflict"]) == 1
    assert "conflicts-truncated" in codes(result)


def test_progress_callback_sees_every_file(mods):
    (mods / "a.package").write_bytes(factories.make_package())
    (mods / "b.txt").write_text("x")
    seen = []
    scanner.scan(str(mods), progress=lambda p, phase: seen.append((p, phase)))
    assert sorted(os.path.basename(p) for p, _ in seen) == ["a.package", "b.txt"]
    assert {phase for _, phase in seen} == {scanner.SCANNING}


def test_progress_reports_the_hashing_phase(mods):
    # Hashing runs after the walk, so it has to report separately or the
    # caller's counter looks frozen.
    data = factories.make_package([factories.key()])
    (mods / "a.package").write_bytes(data)
    (mods / "b.package").write_bytes(data)
    seen = []
    scanner.scan(str(mods), progress=lambda p, phase: seen.append((p, phase)))
    hashed = [p for p, phase in seen if phase == scanner.HASHING]
    assert sorted(os.path.basename(p) for p in hashed) == ["a.package", "b.package"]


def test_missing_folder_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        scanner.scan(str(tmp_path / "nope"))


def test_identical_copies_are_reported_once_as_duplicates(mods):
    data = factories.make_package([factories.key(instance=5)])
    (mods / "a.package").write_bytes(data)
    (mods / "b.package").write_bytes(data)
    result = scanner.scan(str(mods))
    assert codes(result) == {"duplicate"}
