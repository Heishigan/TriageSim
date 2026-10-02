from triagesim.cli import main


def test_check_ok(data_dir, capsys):
    assert main(["cohort", "check", "--data", str(data_dir)]) == 0
    assert "MISSING" not in capsys.readouterr().out


def test_check_fails_and_shows_layout(tmp_path, capsys):
    assert main(["cohort", "check", "--data", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "hosp/" in out and "diagnosis.csv.gz" in out
    assert (tmp_path / "hosp").is_dir()          # empty folders are created for the user


def test_build(data_dir, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["cohort", "build", "--settings", "configs/elderly_falls.yaml",
                 "--data", str(data_dir), "--output", str(out)]) == 0
    assert "First qualifying visit per patient" in capsys.readouterr().out
    assert len(list(out.iterdir())) == 1
