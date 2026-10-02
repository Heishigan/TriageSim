from triagesim import preferences


def test_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIAGESIM_HOME", str(tmp_path))
    assert preferences.load() == {}
    preferences.save({"data_dir": "/x"})
    assert preferences.load() == {"data_dir": "/x"}


def test_corrupt_file_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIAGESIM_HOME", str(tmp_path))
    (tmp_path / "preferences.json").write_text("{not json")
    assert preferences.load() == {}
