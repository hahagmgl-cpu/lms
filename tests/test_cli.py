import json
import os

import pytest

from sims4modcheck import cli, report, scanner
from tests import factories


@pytest.fixture
def mods(tmp_path):
    root = tmp_path / "Mods"
    root.mkdir()
    return root


def test_exit_code_zero_when_clean(mods, capsys):
    (mods / "ok.package").write_bytes(factories.make_package())
    assert cli.main([str(mods), "--quiet"]) == 0
    assert "Nothing broken found." in capsys.readouterr().out


def test_exit_code_one_when_broken(mods, capsys):
    (mods / "dead.package").write_bytes(b"")
    assert cli.main([str(mods), "--quiet"]) == 1
    assert "BROKEN" in capsys.readouterr().out


def test_missing_folder_exits_two(tmp_path, capsys):
    assert cli.main([str(tmp_path / "nope"), "--quiet"]) == 2
    assert "Not a folder" in capsys.readouterr().err


def test_json_output(mods, tmp_path):
    (mods / "dead.package").write_bytes(b"")
    out = tmp_path / "r.json"
    cli.main([str(mods), "--quiet", "--json", str(out)])
    payload = json.loads(out.read_text())
    assert payload["summary"]["errors"] == 1
    assert payload["issues"][0]["code"] == "empty-file"


def test_html_output(mods, tmp_path):
    (mods / "dead.package").write_bytes(b"")
    out = tmp_path / "r.html"
    cli.main([str(mods), "--quiet", "--html", str(out)])
    text = out.read_text()
    assert "<!doctype html>" in text and "dead.package" in text


def test_html_escapes_file_names(mods, tmp_path):
    (mods / "<script>.package").write_bytes(b"")
    result = scanner.scan(str(mods))
    assert "<script>.package" not in report.to_html(result)
    assert "&lt;script&gt;.package" in report.to_html(result)


def test_notes_hidden_unless_all_passed(mods, capsys):
    (mods / "readme.txt").write_text("hi")
    cli.main([str(mods), "--quiet"])
    assert "readme.txt" not in capsys.readouterr().out
    cli.main([str(mods), "--quiet", "--all"])
    assert "readme.txt" in capsys.readouterr().out


def test_quarantine_moves_only_broken_files(mods, tmp_path, capsys):
    (mods / "dead.package").write_bytes(b"")
    (mods / "ok.package").write_bytes(factories.make_package())
    quarantine = tmp_path / "quarantine"
    cli.main([str(mods), "--quiet", "--yes", "--quarantine", str(quarantine)])
    assert not (mods / "dead.package").exists()
    assert (mods / "ok.package").exists()
    assert (quarantine / "dead.package").exists()


def test_quarantine_preserves_subfolders(mods, tmp_path):
    sub = mods / "cc" / "hair"
    sub.mkdir(parents=True)
    (sub / "dead.package").write_bytes(b"")
    quarantine = tmp_path / "q"
    cli.main([str(mods), "--quiet", "--yes", "--quarantine", str(quarantine)])
    assert (quarantine / "cc" / "hair" / "dead.package").exists()


def test_quarantine_declined_by_default(mods, tmp_path, monkeypatch, capsys):
    (mods / "dead.package").write_bytes(b"")
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    cli.main([str(mods), "--quiet", "--quarantine", str(tmp_path / "q")])
    assert (mods / "dead.package").exists()
    assert "Skipped." in capsys.readouterr().out


def test_quarantine_does_not_overwrite_same_named_files(mods, tmp_path):
    for folder in ("a", "b"):
        sub = mods / folder
        sub.mkdir()
        (sub / "dead.package").write_bytes(b"")
    quarantine = tmp_path / "q"
    # Flatten the layout so both files land on the same target name.
    result = scanner.scan(str(mods))
    monkey = [i.path for i in result.errors]
    assert len(monkey) == 2
    cli.main([str(mods), "--quiet", "--yes", "--quarantine", str(quarantine)])
    assert len(list(quarantine.rglob("*.package"))) == 2


def test_unique_suffixes_existing_names(tmp_path):
    path = tmp_path / "a.package"
    path.write_bytes(b"")
    assert os.path.basename(cli._unique(str(path))) == "a (2).package"


def test_quarantine_leaves_merely_misplaced_mods_alone(mods, tmp_path):
    deep = mods / "a" / "b"
    deep.mkdir(parents=True)
    factories.write_script(deep / "healthy.ts4script")
    cli.main([str(mods), "--quiet", "--yes", "--quarantine", str(tmp_path / "q")])
    assert (deep / "healthy.ts4script").exists()


def test_quick_skips_the_slow_passes(mods, capsys):
    # Two identical packages: normally a duplicate, and their shared keys
    # would be compared for conflicts. --quick does neither.
    data = factories.make_package([factories.key()])
    (mods / "a.package").write_bytes(data)
    (mods / "b.package").write_bytes(data)
    cli.main([str(mods), "--quiet", "--quick"])
    out = capsys.readouterr().out
    assert "duplicate" not in out.lower() and "conflict" not in out.lower()
    assert "Nothing broken found." in out


def test_quick_still_finds_broken_mods(mods, capsys):
    (mods / "dead.package").write_bytes(b"")
    assert cli.main([str(mods), "--quiet", "--quick"]) == 1
    assert "dead.package" in capsys.readouterr().out


def test_remove_moves_broken_mods_next_to_the_mods_folder(mods, capsys):
    (mods / "dead.package").write_bytes(b"")
    (mods / "ok.package").write_bytes(factories.make_package())
    cli.main([str(mods), "--quiet", "--yes", "--remove"])
    dest = mods.parent / cli.QUARANTINE_DIRNAME
    assert (dest / "dead.package").exists()
    assert not (mods / "dead.package").exists()
    assert (mods / "ok.package").exists()


def test_remove_destination_is_outside_the_mods_folder(mods):
    # Otherwise the game would just keep loading the broken files.
    (mods / "dead.package").write_bytes(b"")
    cli.main([str(mods), "--quiet", "--yes", "--remove"])
    dest = mods.parent / cli.QUARANTINE_DIRNAME
    assert not str(dest.resolve()).startswith(str(mods.resolve()) + os.sep)


def test_remove_asks_before_touching_anything(mods, monkeypatch, capsys):
    (mods / "dead.package").write_bytes(b"")
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    cli.main([str(mods), "--quiet", "--remove"])
    assert (mods / "dead.package").exists()
    assert "Skipped." in capsys.readouterr().out


def test_remove_lists_what_it_will_take_out(mods, monkeypatch, capsys):
    for n in range(3):
        (mods / f"dead{n}.package").write_bytes(b"")
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    cli.main([str(mods), "--quiet", "--remove"])
    out = capsys.readouterr().out
    assert "dead0.package" in out and "dead2.package" in out
    assert "nothing is deleted" in out


def test_remove_with_nothing_broken_says_so(mods, capsys):
    (mods / "ok.package").write_bytes(factories.make_package())
    cli.main([str(mods), "--quiet", "--yes", "--remove"])
    assert "Nothing to clean up." in capsys.readouterr().out
    assert not (mods.parent / cli.QUARANTINE_DIRNAME).exists()


def test_remove_works_with_quick(mods):
    (mods / "dead.package").write_bytes(b"")
    cli.main([str(mods), "--quiet", "--yes", "--quick", "--remove"])
    assert (mods.parent / cli.QUARANTINE_DIRNAME / "dead.package").exists()


def test_fix_warnings_removes_extra_copies_but_keeps_one(mods):
    data = factories.make_package([factories.key()])
    (mods / "a.package").write_bytes(data)
    sub = mods / "backup"
    sub.mkdir()
    (sub / "a.package").write_bytes(data)
    cli.main([str(mods), "--quiet", "--yes", "--fix-warnings"])
    survivors = list(mods.rglob("a.package"))
    assert len(survivors) == 1, "exactly one copy of a duplicated mod must survive"


def test_fix_warnings_moves_buried_mods_up_instead_of_removing_them(mods):
    deep = mods / "a" / "b" / "c" / "d" / "e" / "f"
    deep.mkdir(parents=True)
    (deep / "buried.package").write_bytes(factories.make_package())
    cli.main([str(mods), "--quiet", "--yes", "--fix-warnings"])
    assert (mods / "buried.package").exists()
    assert not (deep / "buried.package").exists()
    assert not (mods.parent / cli.QUARANTINE_DIRNAME / "buried.package").exists()


def test_fix_warnings_clears_unfinished_downloads(mods):
    (mods / "cc.package.crdownload").write_bytes(b"partial")
    cli.main([str(mods), "--quiet", "--yes", "--fix-warnings"])
    assert not (mods / "cc.package.crdownload").exists()


def test_fix_warnings_never_touches_conflicting_mods(mods):
    # Overriding the same resource is usually deliberate; deleting on that
    # signal would take out working mods.
    shared = [factories.key(instance=7)]
    (mods / "modA.package").write_bytes(factories.make_package(shared))
    (mods / "modB.package").write_bytes(
        factories.make_package(shared + [factories.key(instance=9)])
    )
    cli.main([str(mods), "--quiet", "--yes", "--fix-warnings"])
    assert (mods / "modA.package").exists() and (mods / "modB.package").exists()


def test_fix_warnings_never_touches_unreadable_files(mods, monkeypatch):
    import time as _time

    monkeypatch.setattr(scanner.dbpf, "read_package", lambda *a, **k: _time.sleep(30))
    (mods / "slow.package").write_bytes(factories.make_package())
    cli.main([str(mods), "--quiet", "--yes", "--fix-warnings", "--timeout", "0.5"])
    assert (mods / "slow.package").exists()


def test_delete_permanently_removes(mods):
    (mods / "dead.package").write_bytes(b"")
    cli.main([str(mods), "--quiet", "--yes", "--delete"])
    assert not (mods / "dead.package").exists()
    assert not (mods.parent / cli.QUARANTINE_DIRNAME).exists()


def test_delete_warns_that_there_is_no_undo(mods, monkeypatch, capsys):
    (mods / "dead.package").write_bytes(b"")
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    cli.main([str(mods), "--quiet", "--delete"])
    out = capsys.readouterr().out
    assert "cannot be undone" in out
    assert (mods / "dead.package").exists()


def test_plan_explains_why_each_file_is_going(mods):
    (mods / "dead.package").write_bytes(b"")
    result = scanner.scan(str(mods))
    plan = cli._plan(result, fix_warnings=False)
    assert len(plan) == 1
    action, path, reason = plan[0]
    assert action == "remove" and path.endswith("dead.package") and reason
