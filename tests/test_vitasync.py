import os
import time
from datetime import datetime, timedelta

import pytest

import sync


HOMEBREW_IDS = ["VITASHELL", "SHARKF00D", "SAVEMGR00", "CTMANAGER", "PKGJ00000", "BHBB00001"]
GAME_IDS = ["PCSG00205", "PCSB00244", "PCSE00412", "PCSG01293", "PCSF00249"]


# --- is_game_id ---

def test_is_game_id_known_games_with_database():
    db = set(GAME_IDS)
    for gid in GAME_IDS:
        assert sync.is_game_id(gid, db), f"{gid} should be accepted"


def test_is_game_id_homebrew_excluded_by_database():
    db = set(GAME_IDS)
    for hid in HOMEBREW_IDS:
        assert not sync.is_game_id(hid, db), f"{hid} should be rejected"


def test_is_game_id_regex_fallback_accepts_valid_format():
    for gid in GAME_IDS:
        assert sync.is_game_id(gid, set()), f"{gid} should pass regex"


def test_is_game_id_regex_fallback_rejects_non_format():
    # These don't match [A-Z]{4}\d{5} so regex catches them
    for hid in ["VITASHELL", "SHARKF00D", "SAVEMGR00", "CTMANAGER"]:
        assert not sync.is_game_id(hid, set()), f"{hid} should fail regex"


# --- _parse_game_ids_tsv ---

TSV_SAMPLE = (
    "Title ID\tRegion\tName\tPkg direct link\n"
    "PCSG00205\tJP\tSome Game\thttps://example.com/pkg\n"
    "PCSB00244\tEU\tAnother Game\thttps://example.com/pkg2\n"
    "INVALID__\tXX\tBad ID\thttps://example.com/bad\n"
    "\t\t\t\n"
)


def test_parse_tsv_extracts_valid_ids():
    result = sync._parse_game_ids_tsv(TSV_SAMPLE)
    assert "PCSG00205" in result
    assert "PCSB00244" in result


def test_parse_tsv_rejects_invalid_ids():
    result = sync._parse_game_ids_tsv(TSV_SAMPLE)
    assert "INVALID__" not in result


def test_parse_tsv_skips_empty_rows():
    result = sync._parse_game_ids_tsv(TSV_SAMPLE)
    assert "" not in result


def test_parse_tsv_empty_content():
    assert sync._parse_game_ids_tsv("") == set()
    assert sync._parse_game_ids_tsv("Title ID\tRegion\n") == set()


# --- latest_mtime ---

def test_latest_mtime_empty_dir(tmp_path):
    assert sync.latest_mtime(tmp_path) == 0


def test_latest_mtime_single_file(tmp_path):
    f = tmp_path / "save.bin"
    f.write_bytes(b"data")
    assert sync.latest_mtime(tmp_path) == pytest.approx(f.stat().st_mtime, abs=1.0)


def test_latest_mtime_returns_newest(tmp_path):
    old = tmp_path / "old.bin"
    old.write_bytes(b"old")
    old_mtime = time.time() - 100
    os.utime(old, (old_mtime, old_mtime))

    new = tmp_path / "new.bin"
    new.write_bytes(b"new")

    assert sync.latest_mtime(tmp_path) == pytest.approx(new.stat().st_mtime, abs=1.0)


def test_latest_mtime_nested(tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    f = sub / "deep.bin"
    f.write_bytes(b"x")
    assert sync.latest_mtime(tmp_path) == pytest.approx(f.stat().st_mtime, abs=1.0)


# --- compare_saves ---

def _make_save(path, content=b"data", mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_compare_saves_newer_on_a(tmp_path, monkeypatch):
    old_t = time.time() - 100
    new_t = time.time()

    _make_save(tmp_path / "dev_a" / "PCSG00205" / "save.bin", mtime=new_t)
    _make_save(tmp_path / "dev_b" / "PCSG00205" / "save.bin", mtime=old_t)

    monkeypatch.setattr(sync, "LATEST", tmp_path)
    monkeypatch.setattr(sync, "CONFIG", {"devices": {"dev_a": "1.1.1.1", "dev_b": "2.2.2.2"}})

    actions = sync.compare_saves()
    assert actions == [("PCSG00205", "dev_a", "dev_b")]


def test_compare_saves_newer_on_b(tmp_path, monkeypatch):
    old_t = time.time() - 100
    new_t = time.time()

    _make_save(tmp_path / "dev_a" / "PCSG00205" / "save.bin", mtime=old_t)
    _make_save(tmp_path / "dev_b" / "PCSG00205" / "save.bin", mtime=new_t)

    monkeypatch.setattr(sync, "LATEST", tmp_path)
    monkeypatch.setattr(sync, "CONFIG", {"devices": {"dev_a": "1.1.1.1", "dev_b": "2.2.2.2"}})

    actions = sync.compare_saves()
    assert actions == [("PCSG00205", "dev_b", "dev_a")]


def test_compare_saves_in_sync(tmp_path, monkeypatch):
    t = time.time() - 50

    _make_save(tmp_path / "dev_a" / "PCSG00205" / "save.bin", mtime=t)
    _make_save(tmp_path / "dev_b" / "PCSG00205" / "save.bin", mtime=t)

    monkeypatch.setattr(sync, "LATEST", tmp_path)
    monkeypatch.setattr(sync, "CONFIG", {"devices": {"dev_a": "1.1.1.1", "dev_b": "2.2.2.2"}})

    assert sync.compare_saves() == []


def test_compare_saves_game_only_on_one_device(tmp_path, monkeypatch):
    _make_save(tmp_path / "dev_a" / "PCSG00205" / "save.bin")

    monkeypatch.setattr(sync, "LATEST", tmp_path)
    monkeypatch.setattr(sync, "CONFIG", {"devices": {"dev_a": "1.1.1.1", "dev_b": "2.2.2.2"}})

    actions = sync.compare_saves()
    assert len(actions) == 1
    assert actions[0][0] == "PCSG00205"
    assert actions[0][1] == "dev_a"


# --- hash_save_tree ---

def test_hash_save_tree_empty_dir(tmp_path):
    result = sync.hash_save_tree(tmp_path)
    assert isinstance(result, str) and len(result) == 40


def test_hash_save_tree_stable(tmp_path):
    (tmp_path / "PCSG00205").mkdir()
    (tmp_path / "PCSG00205" / "save.bin").write_bytes(b"data")
    assert sync.hash_save_tree(tmp_path) == sync.hash_save_tree(tmp_path)


def test_hash_save_tree_same_content_same_hash(tmp_path):
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    for d in (d1, d2):
        (d / "PCSG00205").mkdir(parents=True)
        (d / "PCSG00205" / "save.bin").write_bytes(b"savedata")
    assert sync.hash_save_tree(d1) == sync.hash_save_tree(d2)


def test_hash_save_tree_content_change(tmp_path):
    (tmp_path / "save.bin").write_bytes(b"v1")
    h1 = sync.hash_save_tree(tmp_path)
    (tmp_path / "save.bin").write_bytes(b"v2")
    assert sync.hash_save_tree(tmp_path) != h1


def test_hash_save_tree_rename_changes_hash(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"data")
    h1 = sync.hash_save_tree(tmp_path)
    (tmp_path / "a.bin").rename(tmp_path / "b.bin")
    assert sync.hash_save_tree(tmp_path) != h1


def test_hash_save_tree_order_independent(tmp_path):
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    for name, content in [("a.bin", b"aaa"), ("b.bin", b"bbb"), ("c.bin", b"ccc")]:
        (d1 / name).write_bytes(content)
        (d2 / name).write_bytes(content)
    assert sync.hash_save_tree(d1) == sync.hash_save_tree(d2)


# --- due_for_backup ---

def _patched_state(monkeypatch, last_backup=None, last_hash=None):
    s = {
        "last_backup": {("dev" if last_backup is not None else "__x__"): last_backup} if last_backup else {},
        "last_backup_hash": {("dev" if last_hash is not None else "__x__"): last_hash} if last_hash else {},
        "pending": [], "notified": False, "status": "Idle",
    }
    monkeypatch.setattr(sync, "state", s)
    monkeypatch.setattr(sync, "CONFIG", {"backup_hours": 8, "devices": {}})
    return s


def test_due_for_backup_no_prior_backup(monkeypatch):
    _patched_state(monkeypatch)
    assert sync.due_for_backup("dev", "anyhash") is True


def test_due_for_backup_hash_changed(monkeypatch):
    _patched_state(monkeypatch, last_backup=datetime.now(), last_hash="oldhash")
    assert sync.due_for_backup("dev", "newhash") is True


def test_due_for_backup_hash_unchanged_within_interval(monkeypatch):
    _patched_state(monkeypatch, last_backup=datetime.now(), last_hash="samehash")
    assert sync.due_for_backup("dev", "samehash") is False


def test_due_for_backup_hash_unchanged_interval_expired(monkeypatch):
    old = datetime.now() - timedelta(hours=9)
    _patched_state(monkeypatch, last_backup=old, last_hash="samehash")
    assert sync.due_for_backup("dev", "samehash") is True


def test_due_for_backup_no_hash_in_state(monkeypatch):
    s = {
        "last_backup": {"dev": datetime.now()},
        "last_backup_hash": {},
        "pending": [], "notified": False, "status": "Idle",
    }
    monkeypatch.setattr(sync, "state", s)
    monkeypatch.setattr(sync, "CONFIG", {"backup_hours": 8, "devices": {}})
    assert sync.due_for_backup("dev", "anyhash") is True


# --- compare_saves (homebrew filter) ---

def test_compare_saves_ignores_homebrew_dirs(tmp_path, monkeypatch):
    t = time.time() - 100
    new_t = time.time()

    # Homebrew dir only on dev_a with newer mtime - should not appear in actions
    _make_save(tmp_path / "dev_a" / "VITASHELL" / "save.bin", mtime=new_t)
    _make_save(tmp_path / "dev_b" / "VITASHELL" / "save.bin", mtime=t)
    # Real game present on both - should appear
    _make_save(tmp_path / "dev_a" / "PCSG00205" / "save.bin", mtime=new_t)
    _make_save(tmp_path / "dev_b" / "PCSG00205" / "save.bin", mtime=t)

    monkeypatch.setattr(sync, "LATEST", tmp_path)
    monkeypatch.setattr(sync, "CONFIG", {"devices": {"dev_a": "1.1.1.1", "dev_b": "2.2.2.2"}})

    actions = sync.compare_saves()
    game_ids_in_actions = [a[0] for a in actions]
    assert "VITASHELL" not in game_ids_in_actions
    assert "PCSG00205" in game_ids_in_actions
