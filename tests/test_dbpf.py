import pytest

from sims4modcheck import dbpf
from tests import factories


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def test_reads_ts4_header(tmp_path):
    path = write(tmp_path, "a.package", factories.make_package())
    pkg = dbpf.read_package(path)
    assert pkg.is_ts4
    assert pkg.keys == []


def test_reads_resource_keys(tmp_path):
    keys = [factories.key(instance=1), factories.key(instance=2)]
    path = write(tmp_path, "a.package", factories.make_package(keys))
    assert dbpf.read_package(path).keys == keys


def test_reads_keys_with_constant_fields(tmp_path):
    # Real packages hoist repeated fields into the index header.
    keys = [factories.key(instance=1), factories.key(instance=2)]
    data = factories.make_package(keys, index_flags=0b0111)
    path = write(tmp_path, "a.package", data)
    assert dbpf.read_package(path).keys == keys


def test_sims3_package_is_flagged_by_version(tmp_path):
    path = write(tmp_path, "old.package", factories.make_package(major=2, minor=0))
    assert dbpf.read_package(path).is_ts4 is False


def test_empty_file(tmp_path):
    path = write(tmp_path, "a.package", b"")
    with pytest.raises(dbpf.DBPFError, match="empty"):
        dbpf.read_package(path)


def test_truncated_header(tmp_path):
    path = write(tmp_path, "a.package", b"DBPF" + b"\0" * 10)
    with pytest.raises(dbpf.DBPFError, match="truncated"):
        dbpf.read_package(path)


def test_not_a_package(tmp_path):
    path = write(tmp_path, "a.package", b"<!DOCTYPE html>" + b"\0" * 200)
    with pytest.raises(dbpf.DBPFError, match="not a package"):
        dbpf.read_package(path)


def test_index_offset_past_end_of_file(tmp_path):
    data = bytearray(factories.make_package([factories.key()]))
    data[64:68] = (9_000_000).to_bytes(4, "little")
    path = write(tmp_path, "a.package", bytes(data))
    with pytest.raises(dbpf.DBPFError, match="outside the file"):
        dbpf.read_package(path)


def test_absurd_resource_count(tmp_path):
    data = bytearray(factories.make_package([factories.key()]))
    data[36:40] = (5_000_000).to_bytes(4, "little")
    path = write(tmp_path, "a.package", bytes(data))
    with pytest.raises(dbpf.DBPFError, match="too many"):
        dbpf.read_package(path)


def test_truncated_index(tmp_path):
    data = factories.make_package([factories.key(), factories.key(instance=2)])
    path = write(tmp_path, "a.package", data[:-8])
    with pytest.raises(dbpf.DBPFError, match="truncated"):
        dbpf.read_package(path)


def test_read_index_false_skips_index(tmp_path):
    data = factories.make_package([factories.key()])
    path = write(tmp_path, "a.package", data[:-8])
    assert dbpf.read_package(path, read_index=False).keys == []


def test_resource_key_str():
    assert str(factories.key(0xAB, 0xCD, 0xEF)) == "000000AB:000000CD:00000000000000EF"
