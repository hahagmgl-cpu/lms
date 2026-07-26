import zipfile

import pytest

from sims4modcheck import scripts
from tests import factories


def test_reads_game_python_bytecode(tmp_path):
    path = factories.write_script(tmp_path / "m.ts4script")
    mod = scripts.read_script_mod(str(path))
    assert mod.pyc_count == 1
    assert mod.bad_magics == {}


def test_detects_wrong_python_version(tmp_path):
    path = factories.write_script(tmp_path / "m.ts4script", magic=3230)
    mod = scripts.read_script_mod(str(path))
    assert mod.bad_magics == {3230: 1}
    assert scripts.version_for_magic(3230) == "3.3"


def test_counts_uncompiled_sources(tmp_path):
    path = factories.write_script(
        tmp_path / "m.ts4script", names=(), source_names=("a.py", "b.py")
    )
    mod = scripts.read_script_mod(str(path))
    assert (mod.pyc_count, mod.py_source_count) == (0, 2)


def test_ignores_directory_entries(tmp_path):
    path = tmp_path / "m.ts4script"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mod/", "")
    assert scripts.read_script_mod(str(path)).pyc_count == 0


def test_not_a_zip(tmp_path):
    path = tmp_path / "m.ts4script"
    path.write_bytes(b"nonsense")
    with pytest.raises(scripts.ScriptError, match="not a valid zip"):
        scripts.read_script_mod(str(path))


def test_unknown_magic_is_named(tmp_path):
    path = factories.write_script(tmp_path / "m.ts4script", magic=9999)
    mod = scripts.read_script_mod(str(path))
    assert scripts.version_for_magic(next(iter(mod.bad_magics))) == "unknown (magic 9999)"
